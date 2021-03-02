""" Views for interacting with the payment processor. """
import logging
import os
from io import StringIO
from six.moves.urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned
from django.core.management import call_command
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from django.views.generic import RedirectView, TemplateView
from oscar.apps.partner import strategy
from oscar.apps.payment.exceptions import PaymentError
from oscar.core.loading import get_class, get_model

from ecommerce.extensions.basket.utils import basket_add_organization_attribute
from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.extensions.payment.processors.webpay import Webpay, WebpayAlreadyProcessed, WebpayTransactionDeclined

logger = logging.getLogger(__name__)

Applicator = get_class('offer.applicator', 'Applicator')
PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')
NoShippingRequired = get_class('shipping.methods', 'NoShippingRequired')
OrderTotalCalculator = get_class('checkout.calculators', 'OrderTotalCalculator')

class WebpayPaymentNotificationView(EdxOrderPlacementMixin, View):
    """Process the Webpay notification of a completed transaction"""
    @property
    def payment_processor(self):
        return Webpay(self.request.site)

    # Disable atomicity for the view. Otherwise, we'd be unable to commit to the database
    # until the request had concluded; Django will refuse to commit when an atomic() block
    # is active, since that would break atomicity. Without an order present in the database
    # at the time fulfillment is attempted, asynchronous order fulfillment tasks will fail.
    @method_decorator(transaction.non_atomic_requests)
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(WebpayPaymentNotificationView, self).dispatch(request, *args, **kwargs)

    def send_simple_alert_to_eol(self, order_number, site, payed=True, user=None):
        if hasattr(settings, 'BOLETA_CONFIG') and (settings.BOLETA_CONFIG.get('enabled',False)):
            payed_message = "Se realizó el pago exitósamente. "
            if payed:
                payed_message = "No se efectuó pago. "
            user_message = ""
            if user is not None:
                user_message = "Usuario de correo {} y nombre {}. ".format(user.email, user.full_name)
            error_mail_footer = "\nOriginado en {} con partner {}".format(site.domain,site.siteconfiguration.lms_url_root)
            send_mail(
                'Webpay - Error inesperado',
                "Lugar: vista de notificacion de webpay.\nDescripción: {}{}La orden no fue generada con éxito.\n\n".format(user_message,payed_message)+error_mail_footer,
                settings.BOLETA_CONFIG.get("from_email",None),
                [settings.BOLETA_CONFIG.get("team_email","")],
                fail_silently=False
            )

    def _get_basket(self, payment_id):
        """
        Retrieve a basket using a payment ID.
        Arguments:
            payment_id: payment_id received from Webpay.
        Returns:
            It will return related basket or log exception and return None if
            duplicate payment_id received or any other exception occurred.
        """
        try:
            basket = PaymentProcessorResponse.objects.get(
                processor_name=self.payment_processor.NAME,
                transaction_id=payment_id
            ).basket
            basket.strategy = strategy.Default()
            Applicator().apply(basket, basket.owner, self.request)

            basket_add_organization_attribute(basket, self.request.GET)
            return basket
        except MultipleObjectsReturned:
            logger.warning("Duplicate payment ID [%s] received from Webpay.", payment_id)
            return None
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unexpected error during basket retrieval while executing Webpay payment.")
            return None

    def post(self, request):
        """Handle a notification received by Webpay with status update of a transaction"""
        token = request.POST.get("token_ws")
        logger.info("Payment token [%s] update received by Webpay", token)
        try:
            payment = self.payment_processor.get_transaction_data(token)
            if not payment:
                logger.error("Error fetching Webpay details from token [%s]", token)
                raise Http404("Hubo un error al obtener los detalles desde Webpay. ")
        except Exception as e:
            logger.exception("Error receiving payment {} {}".format(request.POST, e))
            raise Http404("Hubo un error al obtener los detalles desde Webpay.")

        try:
            basket = self._get_basket(payment['buy_order'])
            if not basket:
                logger.error("Basket not found for payment [%s]", payment['buy_order'])
                raise Http404("El carrito solicitado no existe.")
        except KeyError:
            logger.exception("Webpay Error, response doesn't have a buy_order because the token is invalid")
            raise Http404("La petición fue cancelada por Webpay. No se ha realizado ningún cobro.")
        except Exception as e:  # pylint: disable=broad-except
            logger.exception("Error receiving payment {} {}".format(request.POST, e))
            raise Http404("El carrito solicitado no existe.")

        order_number = basket.order_number
        try:
            with transaction.atomic():
                try:
                    # payment processor.handle_processor_response
                    self.handle_payment(payment, basket)
                except PaymentError:
                    return redirect(self.payment_processor.error_url)
                except WebpayAlreadyProcessed:
                    # Return 400, telling Webpay that the transaction was already processed
                    raise HttpResponseBadRequest()
                except WebpayTransactionDeclined:
                    # Cancel the basket, as the transaction was declined
                    return redirect(reverse('checkout:cancel-checkout'))
        except HttpResponseBadRequest:
            logger.exception('Payment was already processed [%d] failed.', basket.id)
            raise Http404("El pago ya registra como procesado en ecommerce. Guarde su número de orden {}.".format(order_number))
        except Exception:
            logger.exception('Attempts to handle payment for basket [%d] failed.', basket.id)
            raise Http404("Hubo un error al procesar el carrito. Guarde su número de orden {}.".format(order_number))

        try:
            # Generate and handle the order
            shipping_method = NoShippingRequired()
            shipping_charge = shipping_method.calculate(basket)
            order_total = OrderTotalCalculator().calculate(basket, shipping_charge)

            user = basket.owner

            order = self.handle_order_placement(
                order_number=order_number,
                user=user,
                basket=basket,
                shipping_address=None,
                shipping_method=shipping_method,
                shipping_charge=shipping_charge,
                billing_address=None,
                order_total=order_total,
                request=request
            )
            self.handle_post_order(order)
            
            # Order is created; then send email if enabled
            self.payment_processor.boleta_emission(basket, order)

            return HttpResponseRedirect("{}?order_number={}".format(reverse('checkout:receipt'),order_number))
        except Exception as e:  # pylint: disable=broad-except
            logger.exception(self.order_placement_failure_msg, payment['buy_order'], basket.id)
            raise Http404("Hubo un error al cerrar la orden en ecommerce. Guarde su número de orden {}".format(order_number))
