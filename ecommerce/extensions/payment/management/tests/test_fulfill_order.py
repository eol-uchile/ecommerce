import json
import responses

from oscar.core.loading import get_model, get_class

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils.six import StringIO
from django.test import override_settings

from ecommerce.tests.testcases import TestCase
from ecommerce.extensions.fulfillment.status import ORDER
from ecommerce.extensions.test.factories import create_basket, create_order

PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')
Order = get_model('order', 'Order')


class TestBoletaEmissionsCommand(TestCase):
    """
    Check ecommerce/extensions/fulfillment/tests/test_api for reference
    """

    def create_payment_processor_response(self):
        webpay_response = PaymentProcessorResponse(
            processor_name="webpay",
            transaction_id=self.basket.order_number,
            basket=self.basket,
            response={"token": "token-test", "status": "INITIALIZED"},
        )
        webpay_response.save()

    def setUp(self):
        self.stdout = StringIO()
        self.basket = create_basket(price="10.0")
        self.order_number = self.basket.order_number
        self.create_payment_processor_response()

    def call_command_action(self, *args, **kwargs):
        call_command('fulfill_order',
                     *args,
                     stdout=self.stdout,
                     stderr=StringIO(),
                     **kwargs)

    @responses.activate
    @override_settings(FULFILLMENT_MODULES=['ecommerce.extensions.fulfillment.tests.modules.FakeFulfillmentModule', ])
    def test_complete_order(self):
        self.call_command_action("-l", "{}".format(self.order_number))
        self.assertEqual(ORDER.COMPLETE, Order.objects.first().status)
        # Test idempotency
        self.call_command_action("-l", "{}".format(self.order_number))
        self.assertEqual(1, Order.objects.all().count())
        self.assertEqual(ORDER.COMPLETE, Order.objects.first().status)

    @override_settings(FULFILLMENT_MODULES=['ecommerce.extensions.fulfillment.tests.modules.FakeFulfillmentModule', ])
    def test_skip_no_complete_orders(self):
        self.order = create_order(basket=self.basket)
        self.order.set_status(ORDER.COMPLETE)

        self.call_command_action("-l", "{}".format(self.order_number))
        self.assertEqual(ORDER.COMPLETE, self.order.status)
        self.assertEqual(1, Order.objects.all().count())
        # Test idempotency
        self.call_command_action("-l", "{}".format(self.order_number))
        self.assertEqual(ORDER.COMPLETE, self.order.status)
        self.assertEqual(1, Order.objects.all().count())

    @override_settings(FULFILLMENT_MODULES=['ecommerce.extensions.fulfillment.tests.modules.FakeFulfillmentModule', ])
    def test_fail_on_missing_info(self):
        response = PaymentProcessorResponse.objects.all()
        response.delete()
        self.call_command_action("-l", "{}".format(self.order_number))
        self.assertEqual(0, Order.objects.all().count())
