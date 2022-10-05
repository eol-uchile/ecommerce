import responses
import requests

from collections import namedtuple
from django.test import override_settings
from django.urls import reverse
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, \
    BoletaElectronicaException, BoletaSinFoliosException, make_paragraphs_200, \
    make_boleta_electronica, get_boleta_details, recover_boleta, raise_boleta_error, \
    get_boletas, recover_boleta
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
        self.mock_boleta_auth()
        self.assertEqual({
            "access_token": "test",
            "codigoSII": "codigo sucursal",
            "repCodigo": "codigo reparticion",
            "expires_in": 299},
            authenticate_boleta_electronica(basket=self.basket))
        self.assertEqual(0, self.count_boleta_errors())

    @responses.activate
    def test_authenticate_fail(self):
        self.mock_boleta_auth_refused()
        self.assertRaises(BoletaElectronicaException,
                          authenticate_boleta_electronica, basket=self.basket)
        self.assertEqual(1, self.count_boleta_errors())

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
        self.assertEqual(1, BoletaErrorMessage.objects.all().count())

    def test_raise_boleta_error_save_json(self):
        Dummy_response = namedtuple(
            'Dummy_response', ['text', 'json', 'status_code'])
        response = Dummy_response("error", lambda: {'test': 0}, 404)
        self.assertRaises(BoletaElectronicaException, raise_boleta_error,
                          response, Exception("test"), True, "UA-001")
        self.assertEqual(1, BoletaErrorMessage.objects.all().count())

    @responses.activate
    def test_boleta_success(self):
        self.mock_boleta_auth()
        self.mock_boleta_creation()
        self.mock_boleta_details(self.order.total_incl_tax)
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
        self.mock_boleta_auth()
        self.mock_boleta_creation()
        self.mock_boleta_details_404()
        self.make_billing_info_helper('0', 'CL', self.basket)

        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertEqual("id", make_boleta_electronica(
                self.basket, self.order, auth)["id"])
            # If anything went wrong this would throw an exception
            boleta_o = BoletaElectronica.objects.get(basket=self.basket)
            billing_info = UserBillingInfo.objects.get(
                basket=self.basket, boleta=boleta_o)
            self.assertEqual(0, BoletaErrorMessage.objects.all().count())

    @responses.activate
    def test_boleta_failure(self):
        self.mock_boleta_auth()
        self.mock_boleta_creation_500()
        self.make_billing_info_helper('0', 'CL', self.basket)

        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertRaises(BoletaElectronicaException,
                              make_boleta_electronica, self.basket, self.order, auth)
            # If anything went wrong this would throw an exception
            self.assertEqual(0, BoletaElectronica.objects.all().count())
            self.assertEqual(1, BoletaErrorMessage.objects.all().count())
            self.assertEqual(None, UserBillingInfo.objects.get(
                basket=self.basket).boleta)

    @responses.activate
    def test_get_boleta_details(self):
        self.mock_boleta_auth()
        self.mock_boleta_details(self.order.total_incl_tax)
        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertEqual({
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
        self.mock_boleta_auth()
        auth = authenticate_boleta_electronica()
        self.mock_boleta_details_404()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertRaises(BoletaElectronicaException, get_boleta_details,
                              "id", {
                                  "Authorization": "Bearer " + auth["access_token"]
                              })

    @responses.activate
    def test_get_boletas(self):
        self.mock_boleta_auth()
        self.mock_boleta_get_boletas(
            "2020-03-01T00:00:00",
            total=self.order.total_incl_tax,
            order_number=self.order.number
        )
        auth = authenticate_boleta_electronica()

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertEqual([{
                "boleta": {
                    "fechaEmision": "2020-03-01T00:00:00",
                    "folio": "folio"
                },
                "id": "id",
                "recaudaciones": [{"monto": int(self.order.total_incl_tax), "voucher": self.order.number}]
            }], get_boletas({
                "Authorization": "Bearer " + auth["access_token"]
            }, "2020-03-01T00:00:00"))

    @responses.activate
    def test_get_boletas_error(self):
        self.mock_boleta_auth()
        auth = authenticate_boleta_electronica()
        self.mock_boleta_get_boletas_500("2020-03-01T00:00:00")

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertRaises(BoletaElectronicaException, get_boletas, {
                "Authorization": "Bearer " + auth["access_token"]
            }, "2020-03-01T00:00:00")


class BoletaViewsTests(BoletaMixin, TestCase):
    def create_boleta(self):
        boleta = BoletaElectronica(basket=self.basket, voucher_id="id", receipt_url='{}/ventas/{}/boletas/pdf'.format(
            self.BOLETA_SETTINGS["config_ventas_url"], "id"))
        boleta.save()
        return boleta

    def setUp(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            super(BoletaViewsTests, self).setUp() # Setup TestCases configurations
        self.user = self.create_user()
        self.create_access_token(self.user)
        self.basket = create_basket(owner=self.user, price="10.0")
        self.order = create_order(basket=self.basket)

    def test_recover_boleta_not_configured(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS_DISABLED):
            response = self.client.get(reverse("recover_boleta"))
            self.assertTemplateUsed(response, "404.html")

    def test_recover_boleta_no_login(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            response = self.client.get(reverse("recover_boleta"))
            self.assertTemplateUsed(response, "edx/checkout/boleta_error.html")
            self.assertContains(response, "¡Debe estar autenticado en el sistema!.")

    def test_recover_boleta_no_order_number(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.client.login(username=self.user.username, password=self.password)
            response = self.client.get(reverse("recover_boleta"))
            self.assertTemplateUsed(response, "edx/checkout/boleta_error.html")
            self.assertContains(response, "¡Debe proveer un número de orden!.")

    def test_recover_boleta_doesnt_exists(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.client.login(username=self.user.username, password=self.password)
            response = self.client.get(reverse("recover_boleta"),{"order_number": self.order.number})
            self.assertTemplateUsed(response, "edx/checkout/boleta_error.html")
            self.assertContains(response, "La boleta solicitada no existe.")

    @responses.activate
    def test_recover_boleta_owner(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            boleta = self.create_boleta()
            self.mock_boleta_auth()
            self.mock_boleta_get_file(boleta.voucher_id)
            self.client.login(username=self.user.username, password=self.password)
            response = self.client.get(reverse("recover_boleta"),{"order_number": self.order.number})
            self.assertContains(response, "I'm a PDF file")

    @responses.activate
    def test_recover_boleta_owner_404(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            boleta = self.create_boleta()
            self.mock_boleta_auth()
            self.mock_boleta_get_file_404(boleta.voucher_id)
            self.client.login(username=self.user.username, password=self.password)
            response = self.client.get(reverse("recover_boleta"),{"order_number": self.order.number})
            self.assertTemplateUsed(response, "edx/checkout/boleta_error.html")
            self.assertContains(response, "Hubo un error al recuperar su boleta electrónica.")

    @responses.activate
    def test_recover_boleta_not_owner(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            boleta = self.create_boleta()
            # Change user ownership
            self.basket.owner = self.create_user()
            self.basket.save()
            self.client.login(username=self.user.username, password=self.password)
            response = self.client.get(reverse("recover_boleta"),{"order_number": self.order.number})
            self.assertTemplateUsed(response, "edx/checkout/boleta_error.html")
            self.assertContains(response, "El usuario no es dueño de la orden solicitada.")

    @responses.activate
    def test_recover_boleta_not_owner_but_admin(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            boleta = self.create_boleta()
            # Change user ownership
            self.basket.owner = self.create_user()
            self.basket.save()
            self.mock_boleta_auth()
            self.mock_boleta_get_file(boleta.voucher_id)
            # Add privilege
            self.user.is_superuser = True
            self.user.save()
            self.client.login(username=self.user.username, password=self.password)
            response = self.client.get(reverse("recover_boleta"),{"order_number": self.order.number})
            self.assertContains(response, "I'm a PDF file")
