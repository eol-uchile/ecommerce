import logging
import datetime

from collections import namedtuple
from threadlocals.threadlocals import set_thread_variable

from django.core.management.base import BaseCommand
from django.db import transaction

from oscar.core.loading import get_model, get_class
from oscar.apps.partner import strategy
from oscar.apps.payment.exceptions import PaymentError

from ecommerce.extensions.payment.processors import HandledProcessorResponse
from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.payment.processors.webpay import Webpay

Order = get_model('order','Order')
Basket = get_model('basket','Basket')
NoShippingRequired = get_class('shipping.methods', 'NoShippingRequired')
OrderTotalCalculator = get_class('checkout.calculators', 'OrderTotalCalculator')
PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')
logger = logging.getLogger(__name__)

class OrderPlacer(EdxOrderPlacementMixin):
    """
    Auxiliar class to place orders on behalf of Webpay usign unregistered
    but backend completed transactions
    """
    def __init__(self):
        self.payment_processor_name = "webpay"

    def set_order_variables(self, order_number):
        
        self.order_number = order_number

        responses = PaymentProcessorResponse.objects.filter(
                processor_name=self.payment_processor_name,
                transaction_id=self.order_number
            ).exclude(basket=None)
        responses_count = responses.count()
        if responses_count > 1:
            logger.warning("Got {} processor responses, using first to recover basket".format(responses_count))
        elif responses_count == 0:
            logger.error("Got {} processor responses, using first to recover basket".format(responses_count))
            raise Exception("No responses found for order number {}".format(order_number))
    
        basket = responses.first().basket
        
        basket.strategy = strategy.Default()
        # it may be used to add offers?
        #Applicator().apply(basket, basket.owner, self.request)
        self.basket = basket
        self.site = basket.site

        set_thread_variable("request",namedtuple("request", ["site"])(basket.site))
    
    @property
    def payment_processor(self):
        return Webpay(self.site)

    def get_token(self):
        assert self.basket is not None
        first_payment_response = PaymentProcessorResponse.objects.get(processor_name=self.payment_processor_name, transaction_id=self.order_number)
        return first_payment_response.response["token"]
    
    def create_response(self):
        """
        Create mock response
        """
        token = self.get_token()
        return {
            "manual_response": True,
            "token": token,
            "buy_order": self.order_number,
            "emitted": datetime.datetime.now().isoformat(),
            "status": 'AUTHORIZED',
            "response_code": 0,
            "amount": self.basket.total_incl_tax,
        }

    def create_handled_processor_response(self):
        assert self.basket is not None

        return HandledProcessorResponse(
                    transaction_id=self.basket.order_number,
                    total=self.basket.total_incl_tax, 
                    currency='USD',
                    card_number='webpay_{}'.format(self.basket.id),
                    card_type=None
                )

    def fulfill_order(self):
        if not self.basket:
            logger.error("Basket not found for payment [%s]", self.order_number)
            raise Exception("Basket not found")
        
        # Check if order was already created
        try:
            order = Order.objects.get(number=self.order_number)
            logger.info("Order already completed")
            return
        except Order.DoesNotExist:
            logger.info("Processing order")
        
        try:
            with transaction.atomic():
                try:
                    self.record_payment(self.basket, self.create_handled_processor_response())

                    # Generate and handle the order
                    shipping_method = NoShippingRequired()
                    shipping_charge = shipping_method.calculate(self.basket)
                    order_total = OrderTotalCalculator().calculate(self.basket, shipping_charge)

                    user = self.basket.owner

                    order_number = self.basket.order_number

                    order = self.handle_order_placement(
                        order_number=order_number,
                        user=user,
                        basket=self.basket,
                        shipping_address=None,
                        shipping_method=shipping_method,
                        shipping_charge=shipping_charge,
                        billing_address=None,
                        order_total=order_total
                    )
                    self.handle_post_order(order)
                    
                except PaymentError:
                    raise Exception("Error processing payment.")
            
            # Order is created; then send email if enabled
            self.payment_processor.boleta_emission(self.basket, order)
        except Exception as e:  # pylint: disable=broad-except
            logger.exception(self.order_placement_failure_msg, self.order_number, self.basket.id)
            raise Exception("Error while processing order.")

class Command(BaseCommand):
    help = """Completes order creation for unfulfilled webpay orders.

    Example:
        python manage.py fulfill_order -l EOL-10001 EOL-10002"""
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument("-l", "--list", nargs='+', help="<Required> List of orders separated by space", required=True)

    def handle(self, *args, **options):

        order_placer = OrderPlacer()
        for order in options["list"]:
            try:
                order_placer.set_order_variables(order)
                order_placer.fulfill_order()
            except Exception as e:
                logger.exception("Error processing order {}".format(order))
