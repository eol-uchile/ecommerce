""" Views for interacting with the payment processor. """
import logging

from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from oscar.apps.partner import strategy
from oscar.core.loading import get_class, get_model

from ecommerce.core.url_utils import get_lms_dashboard_url, get_lms_explore_courses_url
from ecommerce.extensions.basket.utils import basket_add_organization_attribute
from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.payment.processors.webpay import Webpay, WebpayAlreadyProcessed, WebpayTransactionDeclined, WebpayRefundRequired
from ecommerce.extensions.payment.views import EolAlertMixin

logger = logging.getLogger(__name__)

Applicator = get_class('offer.applicator', 'Applicator')
PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')
NoShippingRequired = get_class('shipping.methods', 'NoShippingRequired')
OrderTotalCalculator = get_class('checkout.calculators', 'OrderTotalCalculator')

class WebpayPaymentNotificationView(EolAlertMixin, EdxOrderPlacementMixin, View):
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


    def _get_basket(self, payment_id):
        """
        Retrieve a basket using a payment ID.

        CHANGE: In case of duplicate baskets the first will be used.

        Arguments:
            payment_id: payment_id received from Webpay.
        Returns:
            It will return related basket or log exception and return None if
            any exception occurred.
        """
        try:
            payment_responses = PaymentProcessorResponse.objects.filter(
                processor_name=self.payment_processor.NAME,
                transaction_id=payment_id
            )
            if payment_responses.count() > 1:
                logger.warning("Duplicate payment ID [%s] received from Webpay.", payment_id)
            # Always return first basket
            # to avoid double payments
            basket = payment_responses.first().basket
            basket.strategy = strategy.Default()
            Applicator().apply(basket, basket.owner, self.request)

            basket_add_organization_attribute(basket, self.request.GET)
            return basket
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unexpected error during basket retrieval while executing Webpay payment.")
            return None

    def post(self, request):
        """Handle a notification received by Webpay with status update of a transaction"""
        token = request.POST.get("token_ws",'')
        logger.info("Payment token [%s] update received by Webpay", token)
        try:
            payment = self.payment_processor.get_transaction_data(token)
            if not payment:
                raise Exception("No payment response received")
        except Exception as e:
            self.send_simple_alert_to_eol(request.site,"Hubo un error al obtener los detalles desde Webpay. ")
            logger.exception("Error receiving payment {} {}".format(request.POST, e))
            raise Http404("Hubo un error al obtener los detalles desde Webpay.")

        try:
            basket = self._get_basket(payment['buy_order'])
            if not basket:
                raise Exception("Basket not found for payment [%s]", payment['buy_order'])
        except KeyError:
            logger.exception("Webpay Error, response doesn't have a buy_order because the token is invalid")
            #raise Http404("La petición fue cancelada por Webpay. No se ha realizado ningún cobro.")
            return redirect(reverse('checkout:cancel-checkout'))
        except Exception as e:  # pylint: disable=broad-except
            logger.exception("Error receiving payment {} {}".format(request.POST, e))
            self.send_simple_alert_to_eol(request.site,"El carrito solicitado no existe. ", order_number=payment['buy_order'])
            raise Http404("El carrito solicitado no existe.")

        order_number = basket.order_number
        try:
            # Asign token
            payment['token'] = token
            # Calls payment processor.handle_processor_response
            # Verify correct initialization, Commit order on webpay
            # Record response on DB
            self.handle_payment(payment, basket)
        except WebpayTransactionDeclined as webpayException:
            # Cancel the basket, as the transaction was declined
            return HttpResponseRedirect("{}?code={}&order={}".format(reverse('webpay:failure'),webpayException.code, order_number))
            #raise Http404("Transacción declinada por Webpay. Guarde su número de orden {}.".format(order_number))
        except WebpayRefundRequired:
            # Cancel the basket, as the transaction was declined
            self.send_simple_alert_to_eol(request.site,"Inconsistencia en montos de pagos cobrados o pago ya registrado. Se necesita un reembolso. ", order_number=order_number, payed=True, user=basket.owner)
            raise Http404("Hubo un error desde Webpay. Guarde su número de orden {}.".format(order_number))
        except WebpayAlreadyProcessed:
            logger.exception('Payment was already processed [%d] failed.', basket.id)
            self.send_simple_alert_to_eol(request.site,"El pago ya registra como procesado en ecommerce. ", order_number=order_number, payed=True, user=basket.owner)
            raise Http404("El pago ya registra como procesado en ecommerce. Guarde su número de orden {}.".format(order_number))
        except Exception:
            logger.exception('Attempts to handle payment for basket [%d] failed.', basket.id)
            self.send_simple_alert_to_eol(request.site,"Error inesperado al procesar el pago en ecommerce. ", order_number=order_number, payed=True, user=basket.owner)
            raise Http404("Hubo un error al procesar el carrito. Guarde su número de orden {}.".format(order_number))

        # By this point the payment should be confirmed by webpay and our response saved
        # This should allow us to in case of failure, use the fulfill_order command
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
            self.payment_processor.boleta_emission(basket, order, logger)

            return HttpResponseRedirect("{}?order_number={}".format(reverse('checkout:receipt'),order_number))
        except Exception as e:  # pylint: disable=broad-except
            logger.exception(self.order_placement_failure_msg, payment['buy_order'], basket.id)
            self.send_simple_alert_to_eol(request.site,". ", order_number=order_number, payed=True, user=basket.owner)
            raise Http404("Hubo un error al cerrar la orden en ecommerce. Guarde su número de orden {}".format(order_number))

class WebpayErrorView(View):

    def get(self, request):
        code = request.GET.get("code",'')
        order = request.GET.get("order",'')
        # Error context
        context = {
            "payment_support_email": request.site.siteconfiguration.payment_support_email,
            "order_dashboard_url": get_lms_dashboard_url(),
            "explore_courses_url": get_lms_explore_courses_url(),
            "order_number": order,
        }
        # Reference https://www.transbankdevelopers.cl/producto/webpay#codigos-de-respuesta-de-autorizacion
        # but we may just ignore the explanations in the future
        # UPDATED to new codes
        if code == "-1":
            context["msg"] = "Detalle: Tarjeta inválida"
        elif code == "-2":
            context["msg"] = "Detalle: Error de conexión"
        elif code == "-3":
            context["msg"] = "Detalle: Excede monto máximo"
        elif code == "-4":
            context["msg"] = "Detalle: Fecha de expiración inválida"
        elif code == "-5":
            context["msg"] = "Detalle: Problema en autenticación"
        elif code == "-6":
            context["msg"] = "Detalle: Rechazo general"
        elif code == "-7":
            context["msg"] = "Detalle: Tarjeta bloqueada"
        elif code == "-8":
            context["msg"] = "Detalle: Tarjeta vencida"
        elif code == "-9":
            context["msg"] = "Detalle: Transacción no soportada"
        elif code == "-1":
            context["msg"] = "Detalle: Problema en la transacción"
        else:
            # Omit details
            context["msg"] = "Detalle: existe un problema desde Transbank."

        return render(request, "edx/checkout/webpay_error.html",context)
