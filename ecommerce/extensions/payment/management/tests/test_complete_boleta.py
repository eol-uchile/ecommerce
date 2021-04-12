import json
import responses
import datetime

from oscar.core.loading import get_model, get_class

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils.six import StringIO
from django.test import override_settings

from ecommerce.tests.testcases import TestCase
from ecommerce.extensions.fulfillment.status import ORDER
from ecommerce.extensions.payment.models import BoletaElectronica
from ecommerce.extensions.test.factories import create_basket, create_order
from ecommerce.extensions.payment.tests.mixins import BoletaMixin

PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')
Order = get_model('order', 'Order')


class TestBoletaEmissionsCommand(BoletaMixin, TestCase):

    def create_incomplete_boleta(self):
        boleta = BoletaElectronica(
            basket=self.basket,
            voucher_id="id",
            receipt_url="https://receipt-url"
        )
        boleta.save()
        return boleta

    def create_complete_boleta(self):
        boleta = BoletaElectronica(
            basket=self.basket,
            voucher_id="id",
            receipt_url="https://receipt-url",
            folio="folio",
            emission_date=datetime.datetime.now(),
            amount=self.basket.total_incl_tax
        )
        boleta.save()
        return boleta

    def setUp(self):
        self.stdout = StringIO()
        self.basket = create_basket(price="10.0")

    def call_command_action(self, *args, **kwargs):
        call_command('complete_boleta',
                     *args,
                     stdout=self.stdout,
                     stderr=StringIO(),
                     **kwargs)

    def test_skip_if_no_boleta_config(self):
        self.create_incomplete_boleta()

        self.call_command_action()
        boleta = BoletaElectronica.objects.first()
        # Check it stays on default
        self.assertEqual("", boleta.folio)
        self.assertEqual(0, int(boleta.amount))
    
    @responses.activate
    def test_complete_boleta(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.create_incomplete_boleta()
            self.mock_boleta_auth()
            self.mock_boleta_details(self.basket.total_incl_tax)

            self.call_command_action()
            boleta = BoletaElectronica.objects.first()
            self.assertEqual("folio", boleta.folio)
            self.assertEqual(int(self.basket.total_incl_tax),
                             int(boleta.amount))

    @responses.activate
    def test_complete_boleta_list(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.create_incomplete_boleta()
            self.mock_boleta_auth()
            self.mock_boleta_details(self.basket.total_incl_tax)

            self.call_command_action("-l", "{}".format("id"))
            boleta = BoletaElectronica.objects.first()
            self.assertEqual("folio", boleta.folio)
            self.assertEqual(int(self.basket.total_incl_tax),
                             int(boleta.amount))

    @responses.activate
    def test_skip_complete_boleta(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.create_complete_boleta()
            self.mock_boleta_auth()
            self.mock_boleta_details(self.basket.total_incl_tax)

            self.call_command_action()
            boleta = BoletaElectronica.objects.first()
            self.assertEqual("folio", boleta.folio)
            self.assertEqual(int(self.basket.total_incl_tax),
                             int(boleta.amount))

    @responses.activate
    def test_skip_complete_boleta_list(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.create_complete_boleta()
            self.mock_boleta_auth()
            self.mock_boleta_details(self.basket.total_incl_tax)

            self.call_command_action("-l", "{}".format("id"))
            boleta = BoletaElectronica.objects.first()
            self.assertEqual("folio", boleta.folio)
            self.assertEqual(int(self.basket.total_incl_tax),
                             int(boleta.amount))

    @responses.activate
    def test_complete_boleta_dry_run(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.create_incomplete_boleta()

            self.call_command_action("--dry-run")
            boleta = BoletaElectronica.objects.first()
            # Check it stays on default
            self.assertEqual("", boleta.folio)
            self.assertEqual(0, int(boleta.amount))
