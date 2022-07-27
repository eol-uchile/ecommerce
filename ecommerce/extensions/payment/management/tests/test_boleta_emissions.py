import json
import responses

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils.six import StringIO
from django.test import override_settings

from ecommerce.tests.testcases import TestCase
from ecommerce.extensions.fulfillment.status import ORDER
from ecommerce.extensions.payment.models import BoletaElectronica, UserBillingInfo
from ecommerce.extensions.test.factories import create_basket, create_order
from ecommerce.extensions.payment.tests.mixins import BoletaMixin


class TestBoletaEmissionsCommand(BoletaMixin, TestCase):

    def count_boletas(self):
        return BoletaElectronica.objects.all().count()

    def setUp(self):
        self.stdout = StringIO()
        self.basket = create_basket(price="10.0")
        self.order = create_order(basket=self.basket)

    def call_command_action(self, *args, **kwargs):
        call_command('boleta_emissions',
                     *args,
                     stdout=self.stdout,
                     stderr=StringIO(),
                     **kwargs)

    def test_emissions_not_required_basics(self):
        """
        Unused basket, order asociated to basket, no billing_info
        """
        # Open order, no UBI
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

            # Add UBI associated to basket but without boleta
            self.billing_info = self.make_billing_info_helper('0', 'CL',self.basket)
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

            # Add completed status and set UBI.basket to None
            # We can't emit since there's no boleta info
            self.order.status = ORDER.COMPLETE
            self.order.save()
            self.billing_info.basket = None
            self.billing_info.save()
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_emissions_on_complete_order(self):
        self.make_billing_info_helper('0', 'CL',self.basket)
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.mock_boleta_auth()
        self.mock_boleta_creation()
        self.mock_boleta_details(self.order.total_incl_tax)

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())
            # Test idempotency
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())

    @responses.activate
    def test_emissions_for_webpay_payment_processor(self):
        self.make_billing_info_helper('0', 'CL',self.basket, "webpay")
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.mock_boleta_auth()
        self.mock_boleta_creation()
        self.mock_boleta_details(self.order.total_incl_tax)

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.call_command_action("--processor", "webpay")
            self.assertEqual(1, self.count_boletas())
            # Test idempotency
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())

    @responses.activate
    def test_emissions_is_ignored_for_payment_processor(self):
        self.make_billing_info_helper('0', 'CL',self.basket, "paypal")
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.mock_boleta_auth()
        self.mock_boleta_creation()
        self.mock_boleta_details(self.order.total_incl_tax)

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.call_command_action("--processor", "webpay")
            self.assertEqual(0, self.count_boletas())
            # Test idempotency
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())
            
    @responses.activate
    def test_emissions_on_complete_order_without_details(self):
        self.make_billing_info_helper('0', 'CL',self.basket)
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.mock_boleta_auth()
        self.mock_boleta_creation()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())
            # Test idempotency
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())

    @responses.activate
    def test_no_emissions_with_free_order(self):
        self.make_billing_info_helper('0', 'CL',self.basket)
        self.order.status = ORDER.COMPLETE
        self.order.total_incl_tax = 0
        self.order.save()
        product = self.basket.all_lines()[0].product
        product.price_incl_tax = 0
        product.save()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())
            # Test idempotency
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_no_emissions_with_no_valid_orders(self):
        self.make_billing_info_helper('0', 'CL',self.basket)

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.order.status = ORDER.FULFILLMENT_ERROR
            self.order.save()
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

            self.order.status = ORDER.PAYMENT_ERROR
            self.order.save()
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

            self.order.status = ORDER.OPEN
            self.order.save()
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

            self.order.status = ORDER.PENDING
            self.order.save()
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_no_emissions_on_api_403(self):
        self.make_billing_info_helper('0', 'CL',self.basket)
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.mock_boleta_auth_refused()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_no_emissions_on_api_error(self):
        self.make_billing_info_helper('0', 'CL',self.basket)
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.mock_boleta_auth()
        self.mock_boleta_creation_500()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())
            # Test idempotency
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_no_emissions_without_folios_412(self):
        self.make_billing_info_helper('0', 'CL',self.basket)
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.mock_boleta_auth()
        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas',
            status=412
        )

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())
            # Test idempotency
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_skip_emission_on_fulfilled_but_not_associated(self):
        """
        If for some reason there is a boleta emitted but
        it wasn't correctly saved for our workflow we need to 
        account for 
        """
        self.make_billing_info_helper('0', 'CL',self.basket)
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.mock_boleta_auth()
        self.mock_boleta_creation()
        self.mock_boleta_details(self.order.total_incl_tax)

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            # Fulfill
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())

            # Disassociate boleta
            boleta = BoletaElectronica.objects.first()
            boleta.basket = None
            boleta.save()

            # Skip creation since this is a border case
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())

    @responses.activate
    def test_dry_run_emissions_on_complete_order(self):
        self.make_billing_info_helper('0', 'CL',self.basket)
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.mock_boleta_auth()
        self.mock_boleta_creation()
        self.mock_boleta_details(self.order.total_incl_tax)

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.call_command_action("--dry-run")
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_dry_run_emissions_on_complete_order_without_details(self):
        self.make_billing_info_helper('0', 'CL',self.basket)
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.mock_boleta_auth()
        self.mock_boleta_creation()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.call_command_action("--dry-run")
            self.assertEqual(0, self.count_boletas())
