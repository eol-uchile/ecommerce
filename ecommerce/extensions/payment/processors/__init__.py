

import logging
import traceback
import string
import abc
from collections import namedtuple
from itertools import cycle

import waffle
from django.conf import settings
from django.core.mail import send_mail
from django.utils.functional import cached_property
from oscar.core.loading import get_model
from ecommerce.extensions.payment.models import UserBillingInfo, BoletaErrorMessage, PaypalUSDConversion
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, make_boleta_electronica, BoletaElectronicaException

PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')

HandledProcessorResponse = namedtuple('HandledProcessorResponse',
                                      ['transaction_id', 'total', 'currency', 'card_number', 'card_type'])
logger = logging.getLogger(__name__)

class BasePaymentProcessor(metaclass=abc.ABCMeta):  # pragma: no cover
    """Base payment processor class."""

    # NOTE: Ensure that, if passed to a Django template, Django does not attempt to instantiate this class
    # or its children. Doing so without a Site object will cause issues.
    # See https://docs.djangoproject.com/en/1.8/ref/templates/api/#variables-and-lookups
    do_not_call_in_templates = True

    NAME = None

    def __init__(self, site):
        super(BasePaymentProcessor, self).__init__()
        self.site = site

    @abc.abstractmethod
    def get_transaction_parameters(self, basket, request=None, use_client_side_checkout=False, **kwargs):
        """
        Generate a dictionary of signed parameters required for this processor to complete a transaction.

        Arguments:
            use_client_side_checkout:
            basket (Basket): The basket of products being purchased.
            request (Request, optional): A Request object which can be used to construct an absolute URL in
                cases where one is required.
            use_client_side_checkout (bool, optional): Determines if client-side checkout should be used.
            **kwargs: Additional parameters.

        Returns:
            dict: Payment processor-specific parameters required to complete a transaction. At a minimum,
                this dict must include a `payment_page_url` indicating the location of the processor's
                hosted payment page.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def handle_processor_response(self, response, basket=None):
        """
        Handle a response from the payment processor.

        This method creates PaymentEvents and Sources for successful payments.

        Arguments:
            response (dict): Dictionary of parameters received from the payment processor

        Keyword Arguments:
            basket (Basket): Basket whose contents have been purchased via the payment processor

        Returns:
            HandledProcessorResponse
        """
        raise NotImplementedError

    @property
    def configuration(self):
        """
        Returns the configuration (set in Django settings) specific to this payment processor.

        Returns:
            dict: Payment processor configuration

        Raises:
            KeyError: If no settings found for this payment processor
        """
        partner_short_code = self.site.siteconfiguration.partner.short_code
        return settings.PAYMENT_PROCESSOR_CONFIG[partner_short_code.lower()][self.NAME.lower()]

    @property
    def client_side_payment_url(self):
        """
        Returns the URL to which payment data, collected directly from the payment page, should be posted.

        If the payment processor does not support client-side payments, ``None`` will be returned.

        Returns:
            str
        """
        return None

    def record_processor_response(self, response, transaction_id=None, basket=None):
        """
        Save the processor's response to the database for auditing.

        Arguments:
            response (dict): Response received from the payment processor

        Keyword Arguments:
            transaction_id (string): Identifier for the transaction on the payment processor's servers
            basket (Basket): Basket associated with the payment event (e.g., being purchased)

        Return
            PaymentProcessorResponse
        """
        return PaymentProcessorResponse.objects.create(processor_name=self.NAME, transaction_id=transaction_id,
                                                       response=response, basket=basket)

    @abc.abstractmethod
    def issue_credit(self, order_number, basket, reference_number, amount, currency):
        """
        Issue a credit/refund for the specified transaction.

        Arguments:
            order_number (str): Order number of the order being refunded.
            basket (Basket): Basket associated with the order being refunded.
            reference_number (str): Reference number of the transaction being refunded.
            amount (Decimal): amount to be credited/refunded
            currency (string): currency of the amount to be credited

        Returns:
            str: Reference number of the *refund* transaction. Unless the payment processor groups related transactions,
             this will *NOT* be the same as the `reference_number` argument.
        """
        raise NotImplementedError

    @classmethod
    def is_enabled(cls):
        """
        Returns True if this payment processor is enabled, and False otherwise.
        """
        return waffle.switch_is_active(settings.PAYMENT_PROCESSOR_SWITCH_PREFIX + cls.NAME)


class BaseClientSidePaymentProcessor(BasePaymentProcessor, metaclass=abc.ABCMeta):  # pylint: disable=abstract-method
    """ Base class for client-side payment processors. """

    def get_template_name(self):
        """ Returns the path of the template to be loaded for this payment processor.

        Returns:
            str
        """
        return 'payment/{}.html'.format(self.NAME)


class ApplePayMixin:
    @cached_property
    def apple_pay_merchant_id_domain_association(self):
        """ Returns the Apple Pay merchant domain association contents that will be served at
        /.well-known/apple-developer-merchantid-domain-association.

        Returns:
            str
        """
        return (self.configuration.get('apple_pay_merchant_id_domain_association') or '').strip()

class EolBillingMixin:

    VALID_CHARS = string.digits+'Kk'

    def validateRUT(self, rut):
        """
        Verify if the 'rut' is valid
        Reference: https://github.com/eol-uchile/uchileedxlogin/blob/master/uchileedxlogin/views.py#L283
        """
        rut = rut.upper()
        rut = rut.replace("-", "")
        rut = rut.replace(".", "")
        rut = rut.strip()
        aux = rut[:-1]
        dv = rut[-1:]

        revertido = list(map(int, reversed(str(aux))))
        factors = cycle(list(range(2, 8)))
        s = sum(d * f for d, f in zip(revertido, factors))
        res = (-s) % 11

        if str(res) == dv:
            return True
        elif dv == "K" and res == 10:
            return True
        else:
            return False

    def verifyIdNumber(self, request):
        # Before anything verify fields
        id_type = request.data.get("id_option")
        id_number = request.data.get("id_number")
        if id_type == "0":
            # Clean and add dash
            id_number = [c for c in id_number if c in self.VALID_CHARS]
            id_number.insert(-1, "-")
            id_number = "".join(id_number)
            valid_rut = self.validateRUT(id_number)
            if not valid_rut:
                raise Exception("RUT {} Failed Validation".format(id_number))
        
        return id_type, id_number

    def associate_paypal_conversion_rate(self, basket):
        try:
            paypal_conversion = PaypalUSDConversion.objects.first()
            paypal_conversion.basket.add(basket)
            paypal_conversion.save()

        except PaypalUSDConversion.DoesNotExist:
            raise Exception("No Paypal CLP to USD conversion defined")
    
    def remove_from_paypal_conversion_rate(self, basket):
        try:
            paypal_conversion = PaypalUSDConversion.objects.first()
            paypal_conversion.basket.remove(basket)
            paypal_conversion.save()

        except PaypalUSDConversion.DoesNotExist:
            raise Exception("No Paypal CLP to USD conversion defined")

    def createUserBillingInfo(self, request, basket, id_type, id_number, processor="webpay"):
        
        # Stop orders from saving responses and info if finished (Why do I have to write this)
        if basket.status == 'Submitted':
            raise Exception("Orden ya procesada"+str(basket))
        # Overwrite userInfo:
        # sometimes the requests might duplicate
        # and a previous info might exists
        previous_processor = "webpay"
        try:
            user_info = UserBillingInfo.objects.get(basket=basket)
            previous_processor = user_info.payment_processor
            user_info.billing_district = request.data.get("billing_district")
            user_info.billing_city = request.data.get("billing_city")
            user_info.billing_address = request.data.get("billing_address")
            user_info.billing_country_iso2 = request.data.get("billing_country")
            user_info.id_number = id_number
            user_info.id_option = request.data.get("id_option")
            user_info.id_other = request.data.get("id_other")
            user_info.basket = basket
            user_info.first_name = request.data.get("first_name")
            user_info.last_name_1 = request.data.get("last_name_1")
            user_info.last_name_2 = request.data.get("last_name_2")
            user_info.payment_processor = processor
            user_info.save()

        except UserBillingInfo.DoesNotExist:
            UserBillingInfo.objects.create(
                billing_district=request.data.get("billing_district"),
                billing_city=request.data.get("billing_city"),
                billing_address=request.data.get("billing_address"),
                billing_country_iso2=request.data.get("billing_country"),
                id_number=id_number,
                id_option=request.data.get("id_option"),
                id_other=request.data.get("id_other"),
                basket=basket,
                first_name=request.data.get("first_name"),
                last_name_1=request.data.get("last_name_1"),
                last_name_2=request.data.get("last_name_2"),
                payment_processor=processor
            )

        # Associate to paypal (default paypal case)
        if previous_processor == "webpay" and processor == "paypal":
            self.associate_paypal_conversion_rate(basket)
        # Revert paypal case
        elif previous_processor == "paypal" and processor == "webpay":
            self.remove_from_paypal_conversion_rate(basket)
        # Nothing else
        # paypal == paypal
        # webpay == webpay

    def asociateUserInfoToProcessor(self, basket, processor):
        try:
            user_info = UserBillingInfo.objects.get(basket=basket)
            previous_processor = user_info.payment_processor
            user_info.payment_processor = processor
            user_info.save()
            # Associate to paypal (default paypal case)
            if previous_processor == "webpay" and processor == "paypal":
                self.associate_paypal_conversion_rate(basket)
            # Revert paypal case
            elif previous_processor == "paypal" and processor == "webpay":
                self.remove_from_paypal_conversion_rate(basket)        
        except UserBillingInfo.DoesNotExist:
            logger.error("No User Billing info associated to Basket")

    def send_support_email(self, subject, message):
        if hasattr(settings, 'BOLETA_CONFIG') and (settings.BOLETA_CONFIG.get('enabled', False)):
            send_mail(
                    subject, message,
                    settings.BOLETA_CONFIG.get("from_email", None),
                    [settings.BOLETA_CONFIG.get("team_email", "")],
                    fail_silently=False
                )
    
    def boleta_emission(self, basket, order, logger=logger, payment_processor="webpay"):
        """
        Create boleta using Ventas API. Send email if enabled.

        Arguments:
            basket: basket with unit prices
            order: completed order with prices and discounts
        Raises:
            WebpayTransactionDeclined
        """
        if hasattr(settings, 'BOLETA_CONFIG') and (settings.BOLETA_CONFIG.get('enabled', False) and settings.BOLETA_CONFIG.get('generate_on_payment', False)):
            # Boleta can be issued using the boleta_emissions commmand
            # thus we no longer abort payment
            site=basket.site
            error_mail_footer="\nOriginado en {} con partner {}".format(
                site.domain, site.siteconfiguration.lms_url_root)
            try:
                # DATA FLOW FROM WEBPAY TO BOLETA ELECTRONICA
                boleta_auth=authenticate_boleta_electronica(basket=basket)
                boleta_id=make_boleta_electronica(
                    basket,
                    order,
                    boleta_auth,
                    payment_processor
                )
            except BoletaElectronicaException as e:
                logger.error(
                    "BOLETA API HAS FAILED. {}".format(e), exc_info=True)
                try:
                    boleta_error_message=BoletaErrorMessage.objects.get(
                        order_number=basket.order_number)
                    self.send_support_email(
                        'Boleta Electronica API Error(s)',
                        "Lugar: procesador de pago webpay.\nDescripción: Hubo un error al obtener la boleta {}.\n\nCodigo de respuesta {}, mensaje {}\n{}".format(
                            basket.order_number, boleta_error_message.code, boleta_error_message.content, error_mail_footer),
                    )
                    boleta_error_message.delete()
                except BoletaErrorMessage.DoesNotExist:
                    logger.error(
                        "Couldn't find order error message, email not sent.")
                if settings.BOLETA_CONFIG.get("halt_on_boleta_failure", False):
                    raise Exception()
            except Exception as e:
                logger.error(
                    "BOLETA API had an unexpected error? {}".format(e), exc_info=True)
                self.send_support_email(
                    'Boleta Electronica API Error(s)',
                    "Lugar: procesador de pago webpay.\nDescripción: Hubo un error inesperado al obtener una boleta.\n\nError{}\n{}".format(
                        traceback.format_exc(), error_mail_footer),
                )
                if settings.BOLETA_CONFIG.get("halt_on_boleta_failure", False):
                    raise Exception()