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

    def make_boletas(self, number=0, repeat=0):
        boleta_responses = []
        for i in range(number):
            basket = create_basket(price="10.0")
            order = create_order(basket=basket)

            for j in range(repeat):
                boleta_response.append({
                    "boleta": {
                        "fechaEmision": "2020-03-01T00:00:00",
                        "folio": "folio"
                    },
                    "id": "{}-{}".format(i, j),
                    "recaudaciones": [{"monto": int(order.total_incl_tax), "id": order.number}]
                })
                boleta = BoletaElectronica(
                    amount=int(order.total_incl_tax),
                    basket=basket,
                    voucher_id="{}-{}".format(i, j),
                    emission_date="2020-03-01T00:00:00",
                    folio="folio"
                )
                boleta.save()

        return boleta_responses

    def count_boletas(self):
        return BoletaElectronica.objects.all().count()

    def setUp(self):
        self.stdout = StringIO()

    def call_command_action(self, *args, **kwargs):
        call_command('get_boleta_emissions',
                     *args,
                     stdout=self.stdout,
                     stderr=StringIO(),
                     **kwargs)

    @responses.activate
    def test_empty(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.add_boleta_get_boletas_custom("2020-03-01T00:00:00", [])
            self.call_command_action("2020-03-01T00:00:00")
            self.assertEqual(0, self.count_boletas())
