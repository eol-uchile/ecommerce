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


class TestBoletaEmissionsCommand(TestCase):

    boleta_settings = {
        "enabled": True,
        "send_boleta_email": False,
        "generate_on_payment": True,
        "team_email": "test@localhost",
        "halt_on_boleta_failure": True,
        "client_id": "secret",
        "client_secret": "secret",
        "client_scope": "dte:tdo",
        "config_centro_costos": "secret",
        "config_cuenta_contable": "secret",
        "config_sucursal": "secret",
        "config_reparticion": "secret",
        "config_identificador_pos": "secret",
        "config_ventas_url": "https://ventas-test.uchile.cl/ventas-api-front/api/v1",
    }

    def make_billing_info_helper(self, id_type, country_code):
        self.billing_info = UserBillingInfo(
            billing_district="district",
            billing_city="city",
            billing_address="address",
            billing_country_iso2=country_code,
            id_number="1-9",
            id_option=id_type,
            id_other="",
            first_name="name name",
            last_name_1="last name",
            basket=self.basket
        )
        self.billing_info.save()

    def count_boletas(self):
        return BoletaElectronica.objects.all().count()

    def add_auth_to_responses(self):
        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/authorization-token',
            json={"access_token": "test", "codigoSII": "codigo sucursal",
                  "repCodigo": "codigo reparticion"}
        )

    def add_boleta_creation_to_responses(self):
        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas',
            json={"id": "id"}
        )

    def add_boleta_details_to_responses(self):
        responses.add(
            method=responses.GET,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas/id',
            json={
                "boleta": {
                    "fechaEmision": "2020-03-01T00:00:00",
                    "folio": "folio"
                },
                "recaudaciones": [{"monto": int(self.order.total_incl_tax)}]
            }
        )

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
        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

            # Add UBI associated to basket but without boleta
            self.make_billing_info_helper('0', 'CL')
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
        self.make_billing_info_helper('0', 'CL')
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.add_auth_to_responses()
        self.add_boleta_creation_to_responses()
        self.add_boleta_details_to_responses()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())
            # Test idempotency
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())

    @responses.activate
    def test_emissions_on_complete_order_without_details(self):
        self.make_billing_info_helper('0', 'CL')
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.add_auth_to_responses()
        self.add_boleta_creation_to_responses()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())
            # Test idempotency
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())

    @responses.activate
    def test_no_emissions_with_free_order(self):
        self.make_billing_info_helper('0', 'CL')
        self.order.status = ORDER.COMPLETE
        self.order.total_incl_tax = 0
        self.order.save()
        product = self.basket.all_lines()[0].product
        product.price_incl_tax = 0
        product.save()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())
            # Test idempotency
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_no_emissions_with_no_valid_orders(self):
        self.make_billing_info_helper('0', 'CL')

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
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
        self.make_billing_info_helper('0', 'CL')
        self.order.status = ORDER.COMPLETE
        self.order.save()

        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/authorization-token',
            status=403
        )

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_no_emissions_on_api_error(self):
        self.make_billing_info_helper('0', 'CL')
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.add_auth_to_responses()
        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas',
            status=500
        )

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())
            # Test idempotency
            self.call_command_action()
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_no_emissions_without_folios_412(self):
        self.make_billing_info_helper('0', 'CL')
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.add_auth_to_responses()
        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas',
            status=412
        )

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
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
        self.make_billing_info_helper('0', 'CL')
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.add_auth_to_responses()
        self.add_boleta_creation_to_responses()
        self.add_boleta_details_to_responses()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
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
    def test_emit_one_boleta_on_userbillingifo_duplicates(self):

        self.make_billing_info_helper('0', 'CL')
        self.make_billing_info_helper('0', 'CL')
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.add_auth_to_responses()
        self.add_boleta_creation_to_responses()
        self.add_boleta_details_to_responses()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())
            # Idempotency
            self.call_command_action()
            self.assertEqual(1, self.count_boletas())

    @responses.activate
    def test_dry_run_emissions_on_complete_order(self):
        self.make_billing_info_helper('0', 'CL')
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.add_auth_to_responses()
        self.add_boleta_creation_to_responses()
        self.add_boleta_details_to_responses()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.call_command_action("--dry-run")
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_dry_run_emissions_on_complete_order_without_details(self):
        self.make_billing_info_helper('0', 'CL')
        self.order.status = ORDER.COMPLETE
        self.order.save()

        self.add_auth_to_responses()
        self.add_boleta_creation_to_responses()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.call_command_action("--dry-run")
            self.assertEqual(0, self.count_boletas())
