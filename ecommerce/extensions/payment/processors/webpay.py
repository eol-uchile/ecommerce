""" Webpay payment processing. """


import hashlib
import hmac
import logging
import requests
import urllib.request, urllib.parse, urllib.error
from urllib.parse import urljoin
from collections import OrderedDict
from decimal import Decimal
import xml.etree.ElementTree as xml

from django.urls import reverse
from oscar.apps.payment.exceptions import GatewayError, TransactionDeclined
from oscar.core.loading import get_class, get_model

from ecommerce.extensions.payment.processors import BasePaymentProcessor, HandledProcessorResponse
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

        result = requests.post(self.configuration["api_url"]+"/process-webpay", json={
            "notify_url": notify_url.replace("http://","https://"),
            "return_url": return_url.replace("http://","https://"),
            "order_number": basket.order_number,
            "total_incl_tax": basket.total_incl_tax,
            "api_secret": self.configuration["api_secret"]
        })

        if result.status_code == 403 or result.status_code == 500:
            raise GatewayError("Webpay module has failed")

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
                return HandledProcessorResponse(
                    transaction_id=basket.order_number,
                    total=basket.total_incl_tax,
                    currency='CLP',
                    card_number='webpay_{}'.format(basket.id),
                    card_type=None
                )
            else:
                logger.error("Transaction [{}] have different transaction ammount [{}], expected [{}]".format(basket.order_number, response['detailOutput'][0]['amount'], basket.total_incl_tax))

        else:
            logger.error("Transaction [{}] for basket [{}] not done or with invalid amount.\n {}".format(basket.order_number, basket.id, response))
            raise WebpayTransactionDeclined()
        logger.error("Transaction [{}] for basket [{}] not done or with invalid amount.\n {}".format(basket.order_number, basket.id, response))
        raise GatewayError("Transaction not ready")

    def issue_credit(self, order_number, basket, reference_number, amount, currency):
        return reference_number
        raise NotImplementedError

    def get_transaction_data(self, token):
        
        result = requests.post(self.configuration["api_url"]+"/get-transaction", json={
            "api_secret": self.configuration["api_secret"],
            "token": token
        })
        
        if result.status_code == 403 or result.status_code == 500:
            raise GatewayError("Webpay Module is not ready")

        self.record_processor_response(result.json(), transaction_id=None, basket=None)
        return result.json()

    @property
    def notify_url(self):
        """Url for kiphu to notify a successful transaction"""
        return urljoin(get_ecommerce_url(), reverse('webpay:execute'))