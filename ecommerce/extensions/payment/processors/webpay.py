""" Webpay payment processing. """

import logging
import requests
from urllib.parse import urljoin
from decimal import Decimal

from django.urls import reverse
from oscar.apps.payment.exceptions import GatewayError, TransactionDeclined
from oscar.core.loading import get_model

from ecommerce.extensions.payment.processors import BasePaymentProcessor, HandledProcessorResponse, EolBillingMixin
from ecommerce.extensions.payment.exceptions import PartialAuthorizationError
from ecommerce.core.url_utils import get_ecommerce_url

Order = get_model('order', 'Order')

logger = logging.getLogger(__name__)

PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')


class WebpayAlreadyProcessed(Exception):
    """Raised when the order was successful and already processed"""
    pass


class WebpayTransactionDeclined(Exception):
    """Raised when the transaction is declined by webpay

    Attributes:
        code    returned by webpay
        message  explanation of the error
    """

    def __init__(self, code=-1, message="Webpay declined operation with bad code."):
        self.code = code
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return "{}. Code {}".format(self.message, self.code)


class WebpayRefundRequired(Exception):
    """PANIC: Raised when the transaction has been completed with errors"""
    pass


class Webpay(EolBillingMixin, BasePaymentProcessor):
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
        notify_url = self.notify_url

        # Before anything verify fields
        id_type, id_number = self.verifyIdNumber(request)

        result = requests.post(self.configuration["api_url"]+"/process-webpay", json={
            "notify_url": notify_url.replace("http://", "https://"),
            "order_number": basket.order_number,
            "total_incl_tax": basket.total_incl_tax,
            "api_secret": self.configuration["api_secret"]
        })

        if result.status_code == 403 or result.status_code == 500:
            site = basket.site
            self.send_support_email('Webpay Service Error',
             "Lugar: procesador de pago webpay\nDescripción: El servicio de conexión a Webpay falló con código {} al crear la petición inicial.\nEn caso de error 500 revisar los logs del servicio.\nSi el error es 403 las llaves de autenticación se encuentran mal configuradas.\nOrigen {} con partner {}".format(result.status_code, site.domain, site.siteconfiguration.lms_url_root)
             )
            raise GatewayError(
                "Webpay module has failed, error code {}".format(result.status_code))

        result = result.json()

        if result['token'] is None or result['token'] == '':
            msg = 'Webpay payment for basket [%d] declined'

            logger.exception(msg + ': %s', basket.id, result)
            self.record_processor_response(result, basket=basket)
            raise TransactionDeclined(msg, basket.id)

        self.record_processor_response(
            result, transaction_id=basket.order_number, basket=basket)

        parameters = {
            'payment_page_url': result['url'],
            'token_ws': result['token'],
        }

        self.createUserBillingInfo(request, basket, id_type, id_number, self.NAME)

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

        # PART 1: Verify And Commit
        if response['status'] == 'INITIALIZED':
            if Decimal(response['amount']) == Decimal(basket.total_incl_tax):
                # Check if order is already processed
                if Order.objects.filter(number=basket.order_number).exists():
                    raise WebpayAlreadyProcessed()

                commited_response=self.commit_transaction(response['token'])
            else:
                logger.error("Initialized transaction [{}] has different ammount [{}], expected [{}]".format(
                    basket.order_number, response['amount'], basket.total_incl_tax))
                raise PartialAuthorizationError()
        else:
            logger.error("Transaction [{}] for basket [{}] not Initialized.\n {}".format(
                basket.order_number, basket.id, response))
            raise WebpayTransactionDeclined(response['response_code'])

        basket.authorization_code = commited_response['authorization_code'] or ""
        basket.save()
        # Record transaction data
        self.record_processor_response(commited_response, basket=basket)

        # PART 2: Verify commited status
        if commited_response['status'] == 'AUTHORIZED' and commited_response['response_code'] == 0:
            if Decimal(commited_response['amount']) == Decimal(basket.total_incl_tax):

                # Before saving verify that user hasn't payed already
                # by looking if there exists a final processorResponse (basket and no transaction_id)
                response_check=PaymentProcessorResponse.objects.filter(
                    basket=basket, transaction_id=None).values('response')
                # Count AUTHORIZED
                count=0
                for response_item in response_check:
                    if response_item['response']['status'] == 'AUTHORIZED':
                        count=count + 1
                if count > 1:
                    logger.error("REFUND REQUIRED. Transaction [{}] registers as already processed".format(
                        basket.order_number))
                    raise WebpayRefundRequired()

                # Associate final processor
                self.asociateUserInfoToProcessor(basket, self.NAME)

                return HandledProcessorResponse(
                    transaction_id=basket.order_number,
                    total=basket.total_incl_tax,
                    currency='USD',
                    card_number='webpay_{}'.format(basket.id),
                    card_type=None
                )
            else:
                logger.error("REFUND REQUIRED. Transaction [{}] has different ammount [{}], expected [{}]".format(
                    basket.order_number, commited_response['amount'], basket.total_incl_tax))
                raise WebpayRefundRequired()
        else:
            logger.error("Transaction [{}] for basket [{}] not AUTHORIZED\n {}".format(
                basket.order_number, basket.id, commited_response))
            raise WebpayTransactionDeclined(commited_response['response_code'])

    def issue_credit(self, order_number, basket, reference_number, amount, currency):
        raise NotImplementedError()

    def get_transaction_data(self, token):
        """
        Recover transaction data without commiting to webpay
        """
        result=requests.post(self.configuration["api_url"]+"/transaction-status", json={
            "api_secret": self.configuration["api_secret"],
            "token": token
        })

        if result.status_code == 403 or result.status_code == 500:
            self.send_support_email(
                'Webpay Service Error',
                "Lugar: Obtener transaccion (Previo a commit) procesador de pago webpay.\nDescripción: El servicio de conexión a Webpay falló con código {} al obtener estado del token.\nEn caso de error 500 revisar los logs del servicio.\nSi el error es 403 las llaves de autenticación se encuentran mal configuradas.\nNo existe basket para determinar sitio ni partner.".format(result.status_code),
            )
            raise GatewayError(
                "Webpay Module Status is not ready, error code {}".format(result.status_code))

        # Only the first response can be associated to its transaction_id
        self.record_processor_response(
            result.json(), transaction_id=None, basket=None)
        return result.json()

    def commit_transaction(self, token):
        """
        Commit payment on webpay and record the response
        """
        result=requests.post(self.configuration["api_url"]+"/get-transaction", json={
            "api_secret": self.configuration["api_secret"],
            "token": token
        })

        if result.status_code == 403 or result.status_code == 500:
            self.send_support_email(
                'Webpay Service Error',
                "Lugar: procesador de pago webpay.\nDescripción: El servicio de conexión a Webpay falló con código {} al hacer commit.\nEn caso de error 500 revisar los logs del servicio.\nSi el error es 403 las llaves de autenticación se encuentran mal configuradas.\nNo existe basket para determinar sitio ni partner.".format(
                    result.status_code),
            )
            raise GatewayError(
                "Webpay Module is not ready, error code {}".format(result.status_code))
        response=result.json()
        return response

    @property
    def notify_url(self):
        """Url for kiphu to notify a successful transaction"""
        return urljoin(get_ecommerce_url(), reverse('webpay:execute'))
