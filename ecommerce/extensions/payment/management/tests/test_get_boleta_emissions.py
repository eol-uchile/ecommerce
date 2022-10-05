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

    DATE_1 = BoletaMixin.BOLETA_DATE

    def make_boletas(self, number=0, repeat=1):
        boleta_responses = []
        for i in range(number):
            basket = create_basket(price="10.0")
            order = create_order(basket=basket)

            for j in range(repeat):
                boleta_responses.append({
                    "boleta": {
                        "fechaEmision": self.DATE_1,
                        "folio": "folio"
                    },
                    "id": "{}-{}".format(i, j),
                    "referencia": [{"codigoReferencia": order.number}],
                    "puntoVenta": {"rutCajero": basket.order_number},
                    "recaudaciones": [{"monto": int(order.total_incl_tax), "voucher": basket.authorization_code}]
                })
                if j == 0:
                    boleta = BoletaElectronica(
                        amount=int(order.total_incl_tax),
                        basket=basket,
                        voucher_id="{}-{}".format(i, j),
                        emission_date=self.DATE_1,
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
            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, [])
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.call_command_action(self.DATE_1)
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_empty_mail(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, [])
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.call_command_action(self.DATE_1, "--email")
            self.assertEqual(0, self.count_boletas())

    @responses.activate
    def test_one_to_one_match(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            one_boleta = self.make_boletas(number=1)
            self.assertEqual(1, self.count_boletas())

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, one_boleta)
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.call_command_action(self.DATE_1)

    @responses.activate
    def test_one_to_one_match_mail(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            one_boleta = self.make_boletas(number=1)
            self.assertEqual(1, self.count_boletas())

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, one_boleta)
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.call_command_action(self.DATE_1,"--email")

    @responses.activate
    def test_one_to_no_local_fail(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            one_boleta = self.make_boletas(number=1)
            self.assertEqual(1, self.count_boletas())
            BoletaElectronica.objects.all().delete()
            self.assertEqual(0, self.count_boletas())

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, one_boleta)
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.assertRaises(CommandError, self.call_command_action, self.DATE_1)

    @responses.activate
    def test_one_to_no_local_fail_mail(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            one_boleta = self.make_boletas(number=1)
            self.assertEqual(1, self.count_boletas())
            BoletaElectronica.objects.all().delete()
            self.assertEqual(0, self.count_boletas())

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, one_boleta)
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.assertRaises(CommandError, self.call_command_action, self.DATE_1, "--email")

    @responses.activate
    def test_two_to_one_fail(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            two_boletas = self.make_boletas(number=2)
            self.assertEqual(2, self.count_boletas())
            BoletaElectronica.objects.last().delete()
            self.assertEqual(1, self.count_boletas())

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, two_boletas)
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.assertRaises(CommandError, self.call_command_action, self.DATE_1)

    @responses.activate
    def test_two_to_one_fail_mail(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            two_boletas = self.make_boletas(number=2)
            self.assertEqual(2, self.count_boletas())
            BoletaElectronica.objects.last().delete()
            self.assertEqual(1, self.count_boletas())

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, two_boletas)
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.assertRaises(CommandError, self.call_command_action, self.DATE_1, "--email")

    @responses.activate
    def test_two_to_one_fail_v2(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            two_boletas = self.make_boletas(number=2)
            self.assertEqual(2, self.count_boletas())
            BoletaElectronica.objects.last().delete()
            self.assertEqual(1, self.count_boletas())

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, two_boletas, status="INGRESADA")
            self.mock_boleta_get_boletas_custom(self.DATE_1, [])
            self.assertRaises(CommandError, self.call_command_action, self.DATE_1)

    @responses.activate
    def test_two_to_one_fail_v2_mail(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            two_boletas = self.make_boletas(number=2)
            self.assertEqual(2, self.count_boletas())
            BoletaElectronica.objects.last().delete()
            self.assertEqual(1, self.count_boletas())

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, two_boletas, status="INGRESADA")
            self.mock_boleta_get_boletas_custom(self.DATE_1, [])
            self.assertRaises(CommandError, self.call_command_action, self.DATE_1, "--email")

    @responses.activate
    def test_two_to_three_local_fail(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            two_boletas = self.make_boletas(number=2)
            self.assertEqual(2, self.count_boletas())
            basket = create_basket(price="10.0")
            order = create_order(basket=basket)
            boleta = BoletaElectronica(
                    amount=int(order.total_incl_tax),
                    basket=basket,
                    voucher_id="{}-{}".format(10, 4),
                    emission_date=self.DATE_1,
                    folio="folio"
                )
            boleta.save()

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, two_boletas)
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.assertRaises(CommandError, self.call_command_action, self.DATE_1)

    @responses.activate
    def test_two_to_three_local_fail_mail(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            two_boletas = self.make_boletas(number=2)
            self.assertEqual(2, self.count_boletas())
            basket = create_basket(price="10.0")
            order = create_order(basket=basket)
            boleta = BoletaElectronica(
                    amount=int(order.total_incl_tax),
                    basket=basket,
                    voucher_id="{}-{}".format(10, 4),
                    emission_date=self.DATE_1,
                    folio="folio"
                )
            boleta.save()

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, two_boletas)
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.assertRaises(CommandError, self.call_command_action, self.DATE_1, "--email")

    @responses.activate
    def test_two_duplicates_to_one_local_fail(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            two_boletas = self.make_boletas(number=1, repeat=2)
            self.assertEqual(1, self.count_boletas())

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, two_boletas)
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.assertRaises(CommandError, self.call_command_action, self.DATE_1)

    @responses.activate
    def test_two_duplicates_to_one_local_fail_mail(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            two_boletas = self.make_boletas(number=1, repeat=2)
            self.assertEqual(1, self.count_boletas())

            self.mock_boleta_auth()
            self.mock_boleta_get_boletas_custom(self.DATE_1, two_boletas)
            self.mock_boleta_get_boletas_custom(self.DATE_1, [], status="INGRESADA")
            self.assertRaises(CommandError, self.call_command_action, self.DATE_1, "--email")