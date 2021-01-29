import responses
import requests
from unittest.mock import patch 

from django.test import override_settings
from oscar.apps.payment.exceptions import GatewayError, TransactionDeclined
from ecommerce.tests.testcases import TestCase
from ecommerce.extensions.test.factories import create_order
from ecommerce.extensions.payment.exceptions import PartialAuthorizationError
from ecommerce.extensions.payment.processors.webpay import Webpay, WebpayTransactionDeclined
from ecommerce.extensions.payment.tests.processors.mixins import PaymentProcessorTestCaseMixin
from ecommerce.extensions.payment.models import UserBillingInfo, BoletaErrorMessage
from ecommerce.extensions.payment.boleta import BoletaElectronicaException

class WebpayTests(PaymentProcessorTestCaseMixin, TestCase):
    """Tests for the webpay payment processor."""

    processor_class = Webpay
    processor_name = "webpay"

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
            first_name="name name",
            last_name_1="last name",
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
    @patch("django.core.mail.send_mail")
    def test_get_transaction_parameters_webpay_down(self, mock_send_mail):
        mock_send_mail.return_value = True
        responses.add(
            method=responses.POST,
            url='http://transbank:5000/process-webpay',
            status=403
        )
        self.request.data = self.billing_info_form

        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            self.assertRaises(GatewayError, self.processor.get_transaction_parameters,
                self.basket, self.request)

    @responses.activate
    @patch("django.core.mail.send_mail")
    def test_get_transaction_parameters_faulty_response(self, mock_send_mail):
        mock_send_mail.return_value = True
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
    @patch("django.core.mail.send_mail")
    def test_get_transaction_data(self, mock_send_mail):
        mock_send_mail.return_value = True

        transaction_details = self.get_transaction_details_helper()

        responses.add(
            method=responses.POST,
            url='http://transbank:5000/get-transaction',
            json=transaction_details
        )
        response = self.processor.get_transaction_data("token")
        self.assertEqual(transaction_details, response)

    @responses.activate
    @patch("django.core.mail.send_mail")
    def test_get_transaction_data_webpay_down(self, mock_send_mail):
        mock_send_mail.return_value = True
        with override_settings(BOLETA_CONFIG=self.boleta_settings):
            responses.add(  
                method=responses.POST,
                url='http://transbank:5000/get-transaction',
                status=500
            )
            self.assertRaises(
                GatewayError, self.processor.get_transaction_data, "token")

    def test_boleta_emission_disabled(self):    
        self.processor.boleta_emission(self.basket, create_order(basket=self.basket))


    @patch("django.core.mail.send_mail")
    @patch("ecommerce.extensions.payment.boleta.authenticate_boleta_electronica")
    def test_boleta_emission_fail_connection_auth(self, mock_send_mail, mock_auth):
        mock_send_mail.return_value = True

        with override_settings(BOLETA_CONFIG=self.boleta_settings):

            # Create order and make boleta
            order = create_order(basket=self.basket)
            
            mock_auth.side_effect = requests.exceptions.ConnectTimeout

            self.assertRaises(WebpayTransactionDeclined, self.processor.boleta_emission, self.basket, order)


    @patch("django.core.mail.send_mail")
    @patch("ecommerce.extensions.payment.boleta.authenticate_boleta_electronica")
    @patch("ecommerce.extensions.payment.boleta.make_boleta_electronica")
    def test_boleta_emission_fail_connection_post(self, mock_send_mail, mock_auth, mock_boleta):
        mock_send_mail.return_value = True

        with override_settings(BOLETA_CONFIG=self.boleta_settings):

            # Create order and make boleta
            order = create_order(basket=self.basket)
            
            mock_auth.return_value = True
            mock_boleta.side_effect = requests.exceptions.ConnectTimeout

            self.assertRaises(WebpayTransactionDeclined, self.processor.boleta_emission, self.basket, order)

    @patch("django.core.mail.send_mail")
    @patch("ecommerce.extensions.payment.boleta.authenticate_boleta_electronica")
    @patch("ecommerce.extensions.payment.boleta.make_boleta_electronica")
    def test_boleta_emission_fail_boleta_API(self, mock_send_mail, mock_auth, mock_boleta):
        mock_send_mail.return_value = True

        with override_settings(BOLETA_CONFIG=self.boleta_settings):

            # Create order and make boleta
            order = create_order(basket=self.basket)
            
            mock_auth.return_value = True
            mock_boleta.side_effect = BoletaElectronicaException

            # Error creates error description message
            error = BoletaErrorMessage(content="Error test", order_number=order.number, error_at="boleta")

            self.assertRaises(WebpayTransactionDeclined, self.processor.boleta_emission, self.basket, order)

    @patch("django.core.mail.send_mail")
    @patch("ecommerce.extensions.payment.boleta.authenticate_boleta_electronica")
    @patch("ecommerce.extensions.payment.boleta.make_boleta_electronica")
    def test_boleta_emission_fail_unkown_error(self, mock_send_mail, mock_auth, mock_boleta):
        mock_send_mail.return_value = True

        with override_settings(BOLETA_CONFIG=self.boleta_settings):

            # Create order and make boleta
            order = create_order(basket=self.basket)
            
            mock_auth.return_value = True
            mock_boleta.side_effect = Exception

            self.assertRaises(WebpayTransactionDeclined, self.processor.boleta_emission, self.basket, order)

    @responses.activate
    @patch("django.core.mail.send_mail")
    def test_get_transaction_data(self, mock_send_mail):
        mock_send_mail.return_value = True

        transaction_details = self.get_transaction_details_helper()

        responses.add(
            method=responses.POST,
            url='http://transbank:5000/get-transaction',
            json=transaction_details
        )
        response = self.processor.get_transaction_data("token")
        self.assertEqual(transaction_details, response)

    @responses.activate
    @patch("django.core.mail.send_mail")
    def test_get_transaction_data_webpay_down(self, mock_send_mail):
        mock_send_mail.return_value = True
        with override_settings(BOLETA_CONFIG=self.boleta_settings):
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
