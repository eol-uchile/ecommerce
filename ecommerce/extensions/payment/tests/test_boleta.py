import responses
import requests

from collections import namedtuple
from django.test import override_settings
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, \
    BoletaElectronicaException, BoletaSinFoliosException, make_paragraphs_200, \
    make_boleta_electronica, get_boleta_details, recover_boleta, raise_boleta_error
from ecommerce.extensions.payment.models import UserBillingInfo, BoletaElectronica, BoletaErrorMessage

from ecommerce.tests.testcases import TestCase
from ecommerce.extensions.test.factories import create_basket, create_order
from ecommerce.extensions.payment.tests.mixins import BoletaMixin


class BoletaTests(BoletaMixin, TestCase):
    
    def count_boleta_errors(self):
        return BoletaErrorMessage.objects.all().count()

    def make_line(self, number):
        s = ''
        for i in range(number):
            s = s + 'a'
        return s

    def setUp(self):
        self.basket = create_basket(price="10.0")
        self.order = create_order(basket=self.basket)

    def test_make_paragraph_0(self):
        line = self.make_line(0)
        self.assertEqual("^order", make_paragraphs_200(line, "order"))

    def test_make_paragraph_200(self):
        line = self.make_line(200)
        self.assertEqual("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa^order",
                         make_paragraphs_200(line, "order"))

    def test_make_paragraph_400(self):
        line = self.make_line(400)
        self.assertEqual("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa^aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa^aa^order",
                         make_paragraphs_200(line, "order"))

    @responses.activate
    def test_authenticate_success(self):
        self.add_boleta_auth()
        self.assertEqual({"access_token": "test", "codigoSII": "codigo sucursal", "repCodigo": "codigo reparticion"},
                         authenticate_boleta_electronica(basket=self.basket))
        self.assertEquals(0, self.count_boleta_errors())

    @responses.activate
    def test_authenticate_fail(self):
        self.add_boleta_auth_refused()
        self.assertRaises(BoletaElectronicaException,
                          authenticate_boleta_electronica, basket=self.basket)
        self.assertEquals(1, self.count_boleta_errors())

    def test_raise_boleta_error(self):
        Dummy_response = namedtuple(
            'Dummy_response', ['text', 'json', 'status_code'])
        response = Dummy_response("error", None, 404)
        self.assertRaises(BoletaElectronicaException,
                          raise_boleta_error, response, Exception("test"))

    def test_raise_boleta_error_json(self):
        Dummy_response = namedtuple(
            'Dummy_response', ['text', 'json', 'status_code'])
        response = Dummy_response("error", lambda: {'test': 0}, 404)
        self.assertRaises(BoletaElectronicaException,
                          raise_boleta_error, response, Exception("test"))

    def test_raise_boleta_error_save(self):
        Dummy_response = namedtuple(
            'Dummy_response', ['text', 'json', 'status_code'])
        response = Dummy_response("error", None, 404)
        self.assertRaises(BoletaElectronicaException, raise_boleta_error,
                          response, Exception("test"), True, "UA-001")
        self.assertEquals(1, BoletaErrorMessage.objects.all().count())

    def test_raise_boleta_error_save_json(self):
        Dummy_response = namedtuple(
            'Dummy_response', ['text', 'json', 'status_code'])
        response = Dummy_response("error", lambda: {'test': 0}, 404)
        self.assertRaises(BoletaElectronicaException, raise_boleta_error,
                          response, Exception("test"), True, "UA-001")
        self.assertEquals(1, BoletaErrorMessage.objects.all().count())

    @responses.activate
    def test_boleta_success(self):
        self.add_boleta_auth()
        self.add_boleta_creation()
        self.add_boleta_details(self.order.total_incl_tax)
        self.make_billing_info_helper('0', 'CL', self.basket)

        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertEqual("id", make_boleta_electronica(
                self.basket, self.order, auth)["id"])
            # If anything went wrong this would throw an exception
            boleta_o = BoletaElectronica.objects.get(basket=self.basket)
            billing_info = UserBillingInfo.objects.get(
                basket=self.basket, boleta=boleta_o)

    @responses.activate
    def test_boleta_success_no_details(self):
        self.add_boleta_auth()
        self.add_boleta_creation()
        self.add_boleta_details_404()
        self.make_billing_info_helper('0', 'CL', self.basket)

        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertEqual("id", make_boleta_electronica(
                self.basket, self.order, auth)["id"])
            # If anything went wrong this would throw an exception
            boleta_o = BoletaElectronica.objects.get(basket=self.basket)
            billing_info = UserBillingInfo.objects.get(
                basket=self.basket, boleta=boleta_o)
            self.assertEquals(0, BoletaErrorMessage.objects.all().count())

    @responses.activate
    def test_boleta_failure(self):
        self.add_boleta_auth()
        self.add_boleta_creation_500()
        self.make_billing_info_helper('0', 'CL', self.basket)

        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertRaises(BoletaElectronicaException,
                              make_boleta_electronica, self.basket, self.order, auth)
            # If anything went wrong this would throw an exception
            self.assertEquals(0, BoletaElectronica.objects.all().count())
            self.assertEquals(1, BoletaErrorMessage.objects.all().count())
            self.assertEquals(None, UserBillingInfo.objects.get(
                basket=self.basket).boleta)

    @responses.activate
    def test_get_boleta_details(self):
        self.add_boleta_auth()
        self.add_boleta_details(self.order.total_incl_tax)
        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertEquals({
                "boleta": {
                    "fechaEmision": "2020-03-01T00:00:00",
                    "folio": "folio"
                },
                "recaudaciones": [{"monto": int(self.order.total_incl_tax)}]
            }, get_boleta_details("id", {
                "Authorization": "Bearer " + auth["access_token"]
            }))

    @responses.activate
    def test_get_boleta_details_error(self):
        self.add_boleta_auth()
        auth = authenticate_boleta_electronica()
        self.add_boleta_details_404()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertRaises(BoletaElectronicaException, get_boleta_details,
                              "id", {
                                  "Authorization": "Bearer " + auth["access_token"]
                              })
