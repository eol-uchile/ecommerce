import responses

from django.test import override_settings
from oscar.apps.payment.exceptions import GatewayError, TransactionDeclined
from ecommerce.tests.testcases import TestCase
from ecommerce.extensions.payment.exceptions import PartialAuthorizationError
from ecommerce.extensions.payment.processors.webpay import Webpay, WebpayTransactionDeclined
from ecommerce.extensions.payment.tests.processors.mixins import PaymentProcessorTestCaseMixin
from ecommerce.extensions.payment.models import UserBillingInfo


class WebpayTests(PaymentProcessorTestCaseMixin, TestCase):
    """Tests for the webpay payment processor."""

    processor_class = Webpay
    processor_name = "webpay"

    boleta_settings = {
        "enabled": True,
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
            "first_name": "name",
            "last_name_1": "last name",
            "last_name_2": "second last name",
        }

    def get_transaction_details_helper(self):
        """Helper function"""
        return {"accountingDate": "2020-12-23",
                "buyOrder": "order-number",
                "cardDetail": "Last digits",
                              "detailOutput": [{
                                  "sharesNumber": 0,
                                  "amount": float(self.basket.total_incl_tax),
                                  "commerceCode": "commerce-code-secret",
                                  "buyOrder": self.basket.order_number,
                                  "authorizationCode": "secret-auth-code",
                                  "paymentTypeCode": "VD",
                                  "responseCode": 0,  # Success
                              }],
                "sessionId": "string-hash-value",
                "transactionDate": "2020-12-23",
                "urlRedirection": "https://ecommerce.example.com",
                "VCI": "",
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
            first_name="name",
            last_name_1="last name",
            last_name_2="second last name",
            basket=self.basket
        )
        billing_info.save()

    @responses.activate
    def test_get_transaction_parameters(self):
        responses.add(
            method=responses.POST,
            url='http://transbank:5000/process-webpay',
            json={"token": "test-token", "url": "http://webpay.cl"}
        )

        # Append data instead of creating new request
        self.request.data = self.billing_info_form

        response = self.processor.get_transaction_parameters(
            self.basket, request=self.request)

        expected = {
            'payment_page_url': "http://webpay.cl",
            'token_ws': "test-token",
        }

        self.assertEqual(expected, response)
        # Check that billing info was saved
        self.assertIsNotNone(UserBillingInfo.objects.get(basket=self.basket))
        self.assertEqual(UserBillingInfo.RUT,UserBillingInfo.objects.get(basket=self.basket).id_option)

    @responses.activate
    def test_get_transaction_parameters_fail_rut(self):
        responses.add(
            method=responses.POST,
            url='http://transbank:5000/process-webpay',
            json={"token": "test-token", "url": "http://webpay.cl"}
        )

        # Append data instead of creating new request
        self.request.data = self.billing_info_form.copy()
        self.request.data["id_number"] = "13"

        self.assertRaises(Exception,self.processor.get_transaction_parameters,
            self.basket, self.request)


    @responses.activate
    def test_get_transaction_parameters_webpay_down(self):
        responses.add(
            method=responses.POST,
            url='http://transbank:5000/process-webpay',
            status=403
        )
        self.request.data = self.billing_info_form

        self.assertRaises(GatewayError, self.processor.get_transaction_parameters,
            self.basket, self.request)

    @responses.activate
    def test_get_transaction_parameters_faulty_response(self):
        # We test both cases
        responses.add(
            method=responses.POST,
            url='http://transbank:5000/process-webpay',
            json={"token": None, "url": "http://webpay.cl"}
        )

        self.request.data = self.billing_info_form

        self.assertRaises(TransactionDeclined, self.processor.get_transaction_parameters,
            self.basket, self.request)

        responses.add(
            method=responses.POST,
            url='http://transbank:5000/process-webpay',
            json={"token": '', "url": "http://webpay.cl"}
        )
        self.assertRaises(TransactionDeclined, self.processor.get_transaction_parameters,
            self.basket, self.request)

    def test_handle_processor_response(self):

        transaction_details = self.get_transaction_details_helper()

        handled_response = self.processor.handle_processor_response(
            transaction_details, self.basket)
        self.assertEqual(handled_response.total,
                         transaction_details["detailOutput"][0]["amount"])
        self.assertEqual(handled_response.transaction_id,
                         transaction_details["detailOutput"][0]["buyOrder"])

    def test_handle_processor_response_mismatch_error(self):

        transaction_details = self.get_transaction_details_helper()
        transaction_details["detailOutput"][0]["amount"] = -100

        self.assertRaises(PartialAuthorizationError, self.processor.handle_processor_response,
                          transaction_details, self.basket)

    def test_handle_processor_response_webpay_error(self):

        transaction_details = self.get_transaction_details_helper()
        transaction_details["detailOutput"][0]["responseCode"] = 3

        self.assertRaises(WebpayTransactionDeclined, self.processor.handle_processor_response,
                          transaction_details, self.basket)

    @responses.activate
    def test_handle_processor_response_boleta_rut(self):

        transaction_details = self.get_transaction_details_helper()

        self.make_billing_info_helper("0","CL")

        with override_settings(BOLETA_CONFIG=self.boleta_settings):

            responses.add(
                method=responses.POST,
                url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/authorization-token',
                json={"access_token": "test", "codigoSII": "codigo sucursal", "repCodigo": "codigo reparticion"}
            )

            responses.add(
                method=responses.POST,
                url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas',
                json={"id": "test"}
            )

            handled_response = self.processor.handle_processor_response(
                transaction_details, self.basket)
            self.assertEqual(handled_response.total,
                             transaction_details["detailOutput"][0]["amount"])
            self.assertEqual(handled_response.transaction_id,
                             transaction_details["detailOutput"][0]["buyOrder"])
            # Check that billing info was saved
            user_billing_info = UserBillingInfo.objects.get(basket=self.basket)
            self.assertIsNotNone(user_billing_info.boleta)
            self.assertEqual(UserBillingInfo.RUT, user_billing_info.id_option)


    @responses.activate
    def test_handle_processor_response_boleta_passport(self):

        transaction_details = self.get_transaction_details_helper()

        self.make_billing_info_helper("1","FR")

        with override_settings(BOLETA_CONFIG=self.boleta_settings):

            responses.add(
                method=responses.POST,
                url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/authorization-token',
                json={"access_token": "test", "codigoSII": "codigo sucursal", "repCodigo": "codigo reparticion"}
            )

            responses.add(
                method=responses.POST,
                url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas',
                json={"id": "test"}
            )

            handled_response = self.processor.handle_processor_response(
                transaction_details, self.basket)
            self.assertEqual(handled_response.total,
                             transaction_details["detailOutput"][0]["amount"])
            self.assertEqual(handled_response.transaction_id,
                             transaction_details["detailOutput"][0]["buyOrder"])
            # Check that billing info was saved
            user_billing_info = UserBillingInfo.objects.get(basket=self.basket)
            self.assertIsNotNone(user_billing_info.boleta)
            self.assertEqual(UserBillingInfo.PASSPORT, user_billing_info.id_option)

    @responses.activate
    def test_handle_processor_response_no_boleta_fail_settings(self):

        transaction_details = self.get_transaction_details_helper()

        self.make_billing_info_helper("1","US")

        no_fail_settings = self.boleta_settings.copy()
        no_fail_settings["halt_on_boleta_failure"] = False
        with override_settings(BOLETA_CONFIG=no_fail_settings):

            responses.add(
                method=responses.POST,
                url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/authorization-token',
                json={"access_token": "test", "codigoSII": "codigo sucursal", "repCodigo": "codigo reparticion"}
            )

            responses.add(
                method=responses.POST,
                url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/ventas',
                json={"id": "test"}
            )

            handled_response = self.processor.handle_processor_response(
                transaction_details, self.basket)
            self.assertEqual(handled_response.total,
                             transaction_details["detailOutput"][0]["amount"])
            self.assertEqual(handled_response.transaction_id,
                             transaction_details["detailOutput"][0]["buyOrder"])
            # Check that billing info was saved
            user_billing_info = UserBillingInfo.objects.get(basket=self.basket)
            self.assertIsNotNone(user_billing_info.boleta)
            self.assertEqual(UserBillingInfo.PASSPORT, user_billing_info.id_option)

    @responses.activate
    def test_handle_processor_response_boleta_no_connection(self):

        transaction_details = self.get_transaction_details_helper()

        with override_settings(BOLETA_CONFIG=self.boleta_settings):

            responses.add(
                method=responses.POST,
                url='https://ventas-test.uchile.cl/ventas-api-front/api/v1/authorization-token',
                status=403
            )

            self.assertRaises(WebpayTransactionDeclined, self.processor.handle_processor_response,
                              transaction_details, self.basket)

    @responses.activate
    def test_get_transaction_data(self):

        transaction_details = self.get_transaction_details_helper()

        responses.add(
            method=responses.POST,
            url='http://transbank:5000/get-transaction',
            json=transaction_details
        )
        response = self.processor.get_transaction_data("token")
        self.assertEqual(transaction_details, response)

    @responses.activate
    def test_get_transaction_data_webpay_down(self):
        responses.add(
            method=responses.POST,
            url='http://transbank:5000/get-transaction',
            status=500
        )
        self.assertRaises(
            GatewayError, self.processor.get_transaction_data, "token")

    def test_issue_credit(self):
        self.assertRaises(
            NotImplementedError, self.processor.issue_credit, None, None, None, 0, 'CLP')

    def test_issue_credit_error(self):
        self.assertRaises(
            NotImplementedError, self.processor.issue_credit, None, None, None, 0, 'CLP')
