import responses
import requests
from unittest.mock import patch 

from django.test import override_settings
from ecommerce.extensions.payment import boleta
from ecommerce.extensions.payment.models import UserBillingInfo, BoletaElectronica, BoletaErrorMessage

from ecommerce.tests.testcases import TestCase
from ecommerce.extensions.test.factories import create_basket, create_order


class BoletaTests(TestCase):

    boleta_settings = {
        "enabled": True,
        "send_boleta_email": False,
        "generate_on_payment": True,
        "team_email": "test@test.cl",
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

    def make_billing_info_helper(self,id_type,country_code):
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
        self.assertEqual("^order",boleta.make_paragraphs_200(line,"order"))
        
    def test_make_paragraph_200(self):
        line = self.make_line(200)
        self.assertEqual("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa^order",
            boleta.make_paragraphs_200(line,"order"))
    
    def test_make_paragraph_400(self):
        line = self.make_line(400)
        self.assertEqual("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa^aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa^aa^order",
            boleta.make_paragraphs_200(line,"order"))
    
    @responses.activate
    def test_authenticate_success(self):
        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/authorization-token',
            json={"access_token": "test", "codigoSII": "codigo sucursal", "repCodigo": "codigo reparticion"}
        )
        self.assertEqual({"access_token": "test", "codigoSII": "codigo sucursal", "repCodigo": "codigo reparticion"}, 
            boleta.authenticate_boleta_electronica(basket=self.basket))
    
    @responses.activate
    def test_authenticate_fail(self):
        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/authorization-token',
            json={"message": "error auth"},
            status=403
        )
        self.assertRaises(boleta.BoletaElectronicaException, 
            boleta.authenticate_boleta_electronica, basket=self.basket)

    @responses.activate
    def test_boleta_success(self):
        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/authorization-token',
            json={"access_token": "test", "codigoSII": "codigo sucursal", "repCodigo": "codigo reparticion"}
        )

        self.make_billing_info_helper('0', 'CL')

        auth = boleta.authenticate_boleta_electronica()

        responses.add(
            method=responses.POST,
            url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas',
            json={"id": "id"}
        )

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


        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.assertEqual("id", boleta.make_boleta_electronica(self.basket, self.order, auth)["id"])
            # If anything went wrong this would throw an exception
            boleta_o = BoletaElectronica.objects.get(basket=self.basket)
            billing_info = UserBillingInfo.objects.get(basket=self.basket,boleta=boleta_o)
