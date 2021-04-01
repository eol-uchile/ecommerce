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


class BoletaTests(TestCase):

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

    billing_info_form = {
        "billing_district": "district",
        "billing_city": "city",
        "billing_address": "address",
        "billing_country": "CL",
        "id_number": "1-9",
        "id_option": "0",
        "id_other": "",
        "first_name": "first_name last_name",
        "last_name_1": "last_name_1",
        "last_name_2": "",
    }

    def make_billing_info_helper(self, id_type, country_code):
        billing_info = UserBillingInfo(
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
        billing_info.save()

    def count_boleta_errors(self):
        return BoletaErrorMessage.objects.all().count()

    def make_line(self, number):
        s = ''
        for i in range(number):
            s = s + 'a'
        return s

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
        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/authorization-token',
            json={"access_token": "test", "codigoSII": "codigo sucursal",
                  "repCodigo": "codigo reparticion"}
        )
        self.assertEqual({"access_token": "test", "codigoSII": "codigo sucursal", "repCodigo": "codigo reparticion"},
                         authenticate_boleta_electronica(basket=self.basket))
        self.assertEquals(0, self.count_boleta_errors())

    @responses.activate
    def test_authenticate_fail(self):
        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/authorization-token',
            json={"message": "error auth"},
            status=403
        )
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
        self.add_auth_to_responses()
        self.add_boleta_creation_to_responses()
        self.add_boleta_details_to_responses()
        self.make_billing_info_helper('0', 'CL')

        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.assertEqual("id", make_boleta_electronica(
                self.basket, self.order, auth)["id"])
            # If anything went wrong this would throw an exception
            boleta_o = BoletaElectronica.objects.get(basket=self.basket)
            billing_info = UserBillingInfo.objects.get(
                basket=self.basket, boleta=boleta_o)

    @responses.activate
    def test_boleta_success_no_details(self):
        self.add_auth_to_responses()
        self.add_boleta_creation_to_responses()
        responses.add(
            method=responses.GET,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas/id',
            status=500
        )
        self.make_billing_info_helper('0', 'CL')

        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.assertEqual("id", make_boleta_electronica(
                self.basket, self.order, auth)["id"])
            # If anything went wrong this would throw an exception
            boleta_o = BoletaElectronica.objects.get(basket=self.basket)
            billing_info = UserBillingInfo.objects.get(
                basket=self.basket, boleta=boleta_o)
            self.assertEquals(0, BoletaErrorMessage.objects.all().count())

    @responses.activate
    def test_boleta_failure(self):
        self.add_auth_to_responses()
        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas',
            status=500
        )
        self.make_billing_info_helper('0', 'CL')

        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.assertRaises(BoletaElectronicaException,
                              make_boleta_electronica, self.basket, self.order, auth)
            # If anything went wrong this would throw an exception
            self.assertEquals(0, BoletaElectronica.objects.all().count())
            self.assertEquals(1, BoletaErrorMessage.objects.all().count())
            self.assertEquals(None, UserBillingInfo.objects.get(
                basket=self.basket).boleta)

    @responses.activate
    def test_get_boleta_details(self):
        self.add_auth_to_responses()
        self.add_boleta_details_to_responses()
        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
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
        self.add_auth_to_responses()
        auth = authenticate_boleta_electronica()

        responses.add(
            method=responses.GET,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas/id',
            status=404
        )

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.assertRaises(BoletaElectronicaException, get_boleta_details,
                              "id", {
                                  "Authorization": "Bearer " + auth["access_token"]
                              })
