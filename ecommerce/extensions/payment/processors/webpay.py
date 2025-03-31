""" Webpay payment processing. """


import hashlib
import hmac
import logging
import requests
import traceback
import urllib.request, urllib.parse, urllib.error
from urllib.parse import urljoin
from collections import OrderedDict
from decimal import Decimal
from itertools import cycle
import xml.etree.ElementTree as xml

from django.urls import reverse
from django.conf import settings
from django.core.mail import send_mail
from oscar.apps.payment.exceptions import GatewayError, TransactionDeclined
from oscar.core.loading import get_class, get_model

from ecommerce.extensions.payment.processors import BasePaymentProcessor, HandledProcessorResponse
from ecommerce.extensions.payment.models import UserBillingInfo, BoletaErrorMessage
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, make_boleta_electronica, BoletaElectronicaException
from ecommerce.extensions.payment.exceptions import PartialAuthorizationError
from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.core.url_utils import get_ecommerce_url

Order = get_model('order', 'Order')

logger = logging.getLogger(__name__)

class WebpayAlreadyProcessed(Exception):
    """Raised when the order was successful and already processed"""
    pass

class WebpayTransactionDeclined(Exception):
    """Raised when the transaction is declined by webpay"""
    pass

class Webpay(BasePaymentProcessor):
    """
    Webpay PLUS
    """
    NAME = 'webpay'
    DEFAULT_PROFILE_NAME = 'default'

    def __init__(self, site):
        """
        Construct a new instance of the Webpay processor.
        """
        super(Webpay, self).__init__(site)

    def validarRut(self, rut):
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

    def get_transaction_parameters(self, basket, request=None, use_client_side_checkout=False, **kwargs):
        """
        Create a new Webpay payment.
        Arguments:
            basket (Basket): The basket of products being purchased.
            request (Request, optional): A Request object which is used to construct Webpay's `return_url`.
            use_client_side_checkout (bool, optional): This value is not used.
            **kwargs: Additional parameters; not used by this method.
        Returns:
            dict: Webpay-specific parameters required to complete a transaction. Must contain a URL
                to which users can be directed in order to approve a newly created payment.
        Raises:
            GatewayError: Indicates a general error or unexpected behavior on the part of Webpay which prevented
                a payment from being created.
            TransactionDeclined: Indicates that Webpay declined to create the transaction.
        """
        #return_url = get_receipt_page_url(
        #    order_number=basket.order_number,
        #    site_configuration=basket.site.siteconfiguration
        #)
        return_url = urljoin(get_ecommerce_url(), reverse('webpay:return', kwargs={'order_number': basket.order_number}))
        notify_url = self.notify_url


        # Before anything verify fields
        id_type = request.data.get("id_option")
        if id_type == "0":
            valid_rut = self.validarRut(request.data.get("id_number"))
            if not valid_rut:
                raise Exception("Failed RUT validation")

        result = requests.post(self.configuration["api_url"]+"/process-webpay", json={
            "notify_url": notify_url.replace("http://","https://"),
            "return_url": return_url.replace("http://","https://"),
            "order_number": basket.order_number,
            "total_incl_tax": basket.total_incl_tax,
            "api_secret": self.configuration["api_secret"]
        })

        if result.status_code == 403 or result.status_code == 500:
            send_mail(
                'Webpay Service Error',
                "Lugar: procesador de pago webpay\nDescripción: El servicio de conexión a Webpay falló con código {}.\nEn caso de error 500 revisar los logs del servicio.\nSi el error es 403 las llaves de autenticación se encuentran mal configuradas.".format(result.status_code),
                settings.BOLETA_CONFIG.get("from_email",None),
                [settings.BOLETA_CONFIG.get("team_email","")],
                fail_silently=False
            )
            raise GatewayError("Webpay module has failed, error code {}".format(result.status_code))

        result = result.json()

        if result['token'] is None or result['token'] == '':
            msg = 'Webpay payment for basket [%d] declined'

            logger.exception(msg + ': %s', basket.id, result)
            self.record_processor_response(result, basket=basket)
            raise TransactionDeclined(msg, basket.id)

        self.record_processor_response(result, transaction_id=basket.order_number, basket=basket)

        parameters = {
            'payment_page_url': result['url'],
            'token_ws': result['token'],
        }

        # After all is ready register the billing info
        billing_info = UserBillingInfo(
            billing_district=request.data.get("billing_district"),
            billing_city=request.data.get("billing_city"),
            billing_address=request.data.get("billing_address"),
            billing_country_iso2=request.data.get("billing_country"),
            id_number=request.data.get("id_number"),
            id_option=request.data.get("id_option"),
            id_other=request.data.get("id_other"),
            basket=basket,
            first_name=request.data.get("first_name"),
            last_name_1=request.data.get("last_name_1"),
            last_name_2=request.data.get("last_name_2"))
        billing_info.save()

        return parameters

    def handle_processor_response(self, response, basket):
        """
        Handle Webpay notification, completing the transaction if the parameters are correct.
        Arguments:
            response: Dictionary with the transaction data fetched from self.get_transaction_data
            basket: Basket assigned to the transaction
        Returns:
            HandledProcessorResponse with the transaction information
        Raises:
            GatewayError: Indicates the transaction is not ready, or the amount isn't the same as recorded
        """
        # Fetch transfaction data
        self.record_processor_response(response, basket=basket)

        if response['detailOutput'][0]['responseCode'] == 0:
            if Decimal(response['detailOutput'][0]['amount']) == Decimal(basket.total_incl_tax):
                # Check if order is already processed
                if Order.objects.filter(number=basket.order_number).exists():
                    raise WebpayAlreadyProcessed()
                
                if hasattr(settings, 'BOLETA_CONFIG') and (settings.BOLETA_CONFIG.get('enabled',False) and settings.BOLETA_CONFIG.get('generate_on_payment',False)):
                    # Boleta can be issued using the boleta_emissions commmand
                    # thus we no longer abort payment
                    try:
                        # DATA FLOW FROM WEBPAY TO BOLETA ELECTRONICA
                        boleta_auth = authenticate_boleta_electronica(basket=basket)
                        boleta_id = make_boleta_electronica(
                            basket,
                            basket.total_incl_tax,
                            boleta_auth
                        )
                    except requests.exceptions.ConnectTimeout:
                        logger.error("BOLETA API couldn't connect. {}".format(e))
                        send_mail(
                            'Boleta Electronica API Error(s)',
                            "Lugar: procesador de pago webpay.\nDescripción: No se pudo establecer la conexión a la API de Boleta electronica.\nEl nombre no fue resuelto resultando en una request.exceptions.ConnectTimeout.",
                            settings.BOLETA_CONFIG.get("from_email",None),
                            [settings.BOLETA_CONFIG.get("team_email","")],
                            fail_silently=False
                        )
                        if settings.BOLETA_CONFIG.get("halt_on_boleta_failure",False):
                            raise WebpayTransactionDeclined()
                    except BoletaElectronicaException as e:
                        logger.error("BOLETA API HAS FAILED. {}".format(e), exc_info=True)
                        try:
                            boleta_error_message = BoletaErrorMessage.objects.get(order_number=basket.order_number)
                            send_mail(
                                'Boleta Electronica API Error(s)',
                                "Lugar: procesador de pago webpay.\nDescripción: Hubo un error al obtener la boleta {}.\n\nCodigo de respuesta {}, mensaje {}".format(basket.order_number,boleta_error_message.code,boleta_error_message.content),
                                settings.BOLETA_CONFIG.get("from_email",None),
                                [settings.BOLETA_CONFIG.get("team_email","")],
                                fail_silently=False
                            )
                            boleta_error_message.delete()
                        except BoletaErrorMessage.DoesNotExist:
                            logger.error("Couldn't find order error message, email not sent.")
                        if settings.BOLETA_CONFIG.get("halt_on_boleta_failure",False):
                            raise WebpayTransactionDeclined()
                    except Exception as e:
                        logger.error("BOLETA API had an unexpected error? {}".format(e), exc_info=True)
                        send_mail(
                            'Boleta Electronica API Error(s)',
                            "Lugar: procesador de pago webpay.\nDescripción: Hubo un error inesperado al obtener una boleta.\n\nError{}".format(traceback.format_exc()),
                            settings.BOLETA_CONFIG.get("from_email",None),
                            [settings.BOLETA_CONFIG.get("team_email","")],
                            fail_silently=False
                        )
                        if settings.BOLETA_CONFIG.get("halt_on_boleta_failure",False):
                            raise WebpayTransactionDeclined()

                return HandledProcessorResponse(
                    transaction_id=basket.order_number,
                    total=basket.total_incl_tax, 
                    currency='USD',
                    card_number='webpay_{}'.format(basket.id),
                    card_type=None
                )
            else:
                logger.error("Transaction [{}] have different transaction ammount [{}], expected [{}]".format(basket.order_number, response['detailOutput'][0]['amount'], basket.total_incl_tax))
                raise PartialAuthorizationError()
        else:
            logger.error("Transaction [{}] for basket [{}] not done or with invalid amount.\n {}".format(basket.order_number, basket.id, response))
            raise WebpayTransactionDeclined()
        logger.error("Transaction [{}] for basket [{}] not done or with invalid amount.\n {}".format(basket.order_number, basket.id, response))
        raise GatewayError("Transaction not ready")

    def issue_credit(self, order_number, basket, reference_number, amount, currency):
        raise NotImplementedError

    def get_transaction_data(self, token):
        
        result = requests.post(self.configuration["api_url"]+"/get-transaction", json={
            "api_secret": self.configuration["api_secret"],
            "token": token
        })
        
        if result.status_code == 403 or result.status_code == 500:
            send_mail(
                'Webpay Service Error',
                "El servicio de conexión a Webpay falló con código {}.\nEn caso de error 500 revisar los logs del servicio.\nSi el error es 403 las llaves de autenticación se encuentran mal configuradas.".format(result.status_code),
                settings.BOLETA_CONFIG.get("from_email",None),
                [settings.BOLETA_CONFIG.get("team_email","")],
                fail_silently=False
            )
            raise GatewayError("Webpay Module is not ready, error code {}".format(result.status_code))

        self.record_processor_response(result.json(), transaction_id=None, basket=None)
        return result.json()

    @property
    def notify_url(self):
        """Url for kiphu to notify a successful transaction"""
        return urljoin(get_ecommerce_url(), reverse('webpay:execute'))