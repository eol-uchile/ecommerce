import responses
import requests
from unittest.mock import patch

from django.test import override_settings
from oscar.apps.payment.exceptions import GatewayError, TransactionDeclined
from ecommerce.tests.testcases import TestCase
from ecommerce.extensions.test.factories import create_order
from ecommerce.extensions.payment.exceptions import PartialAuthorizationError
from ecommerce.extensions.payment.processors.webpay import Webpay, WebpayTransactionDeclined, WebpayRefundRequired
from ecommerce.extensions.payment.tests.processors.mixins import PaymentProcessorTestCaseMixin
from ecommerce.extensions.payment.tests.mixins import BoletaMixin, TransbankMixin
from ecommerce.extensions.payment.models import UserBillingInfo, BoletaErrorMessage
from ecommerce.extensions.payment.boleta import BoletaElectronicaException


class WebpayTests(TransbankMixin, BoletaMixin, PaymentProcessorTestCaseMixin, TestCase):
    """Tests for the webpay payment processor."""

    processor_class = Webpay
    processor_name = "webpay"

    @responses.activate
    def test_get_transaction_parameters(self):

        self.mock_transbank_initial_token_response()

        # Append data instead of creating new request
        self.request.data = self.BILLING_INFO_FORM

        response = self.processor.get_transaction_parameters(
            self.basket, request=self.request)

        expected = {
            'payment_page_url': "http://webpay.cl",
            'token_ws': "test-token",
        }

        self.assertEqual(expected, response)
        # Check that billing info was saved
        self.assertIsNotNone(UserBillingInfo.objects.get(basket=self.basket))
        self.assertEqual(UserBillingInfo.RUT, UserBillingInfo.objects.get(
            basket=self.basket).id_option)

    @responses.activate
    def test_get_transaction_parameters_fail_rut(self):
        self.mock_transbank_initial_token_response()

        # Append data instead of creating new request
        self.request.data = self.BILLING_INFO_FORM.copy()
        self.request.data["id_number"] = "13"

        self.assertRaises(Exception, self.processor.get_transaction_parameters,
                          self.basket, self.request)

    @responses.activate
    @patch("django.core.mail.send_mail")
    def test_get_transaction_parameters_webpay_down(self, mock_send_mail):
        mock_send_mail.return_value = True
        self.mock_transbank_initial_token_response_error(403)
        self.request.data = self.BILLING_INFO_FORM

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.assertRaises(GatewayError, self.processor.get_transaction_parameters,
                              self.basket, self.request)

    @responses.activate
    @patch("django.core.mail.send_mail")
    def test_get_transaction_parameters_faulty_response(self, mock_send_mail):
        mock_send_mail.return_value = True
        # We test both cases
        self.mock_transbank_initial_token_response(
            {"token": None, "url": "http://webpay.cl"})

        self.request.data = self.BILLING_INFO_FORM

        self.assertRaises(TransactionDeclined, self.processor.get_transaction_parameters,
                          self.basket, self.request)

        self.mock_transbank_initial_token_response(
            {"token": '', "url": "http://webpay.cl"})
        self.assertRaises(TransactionDeclined, self.processor.get_transaction_parameters,
                          self.basket, self.request)

    @responses.activate
    def test_handle_processor_response(self):

        self.mock_transbank_response('AUTHORIZED', float(
            self.basket.total_incl_tax), self.basket.order_number, 0)

        transaction_details = self.get_transaction_details_helper('INITIALIZED', float(
            self.basket.total_incl_tax), self.basket.order_number, 0)
        transaction_details['token'] = "test"

        handled_response = self.processor.handle_processor_response(
            transaction_details, self.basket)
        self.assertEqual(handled_response.total,
                         transaction_details["amount"])
        self.assertEqual(handled_response.transaction_id,
                         transaction_details["buy_order"])

    def test_handle_processor_response_mismatch_error(self):

        transaction_details = self.get_transaction_details_helper(
            'INITIALIZED', -100, self.basket.order_number, None)
        transaction_details['token'] = "test"

        self.assertRaises(PartialAuthorizationError, self.processor.handle_processor_response,
                          transaction_details, self.basket)

    def test_handle_processor_response_webpay_error(self):

        transaction_details = self.get_transaction_details_helper('INITIALIZEDs', float(
            self.basket.total_incl_tax), self.basket.order_number, None)
        transaction_details['token'] = "test"

        self.assertRaises(WebpayTransactionDeclined, self.processor.handle_processor_response,
                          transaction_details, self.basket)

    @responses.activate
    def test_handle_processor_response_webpay_refund_required(self):

        transaction_details = self.get_transaction_details_helper(
            'INITIALIZED', float(self.basket.total_incl_tax), self.basket.order_number, 0)
        transaction_details['token'] = "test"

        self.mock_transbank_response(
            'AUTHORIZED', 1, self.basket.order_number, 0)

        self.assertRaises(WebpayRefundRequired, self.processor.handle_processor_response,
                          transaction_details, self.basket)

    @responses.activate
    @patch("django.core.mail.send_mail")
    def test_get_transaction_data(self, mock_send_mail):
        mock_send_mail.return_value = True

        self.mock_transbank_status_response('INITIALIZED', float(
            self.basket.total_incl_tax), self.basket.order_number, 0)
        transaction_details = self.get_transaction_details_helper(
            'INITIALIZED', float(self.basket.total_incl_tax), self.basket.order_number, 0)

        response = self.processor.get_transaction_data("token")
        self.assertEqual(transaction_details, response)

    @responses.activate
    @patch("django.core.mail.send_mail")
    def test_get_transaction_data_webpay_down(self, mock_send_mail):
        mock_send_mail.return_value = True
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.mock_transbank_status_response_error()
            self.assertRaises(
                GatewayError, self.processor.get_transaction_data, "token")

    @responses.activate
    @patch("django.core.mail.send_mail")
    def test_commit_transaction(self, mock_send_mail):
        mock_send_mail.return_value = True

        transaction_details = self.get_transaction_details_helper(
            'AUTHORIZED', float(self.basket.total_incl_tax), self.basket.order_number, 0)

        self.mock_transbank_response(
            'AUTHORIZED', float(self.basket.total_incl_tax), self.basket.order_number, 0)
        response = self.processor.commit_transaction("token")
        self.assertEqual(transaction_details, response)

    @responses.activate
    @patch("django.core.mail.send_mail")
    def test_commit_transaction_webpay_down(self, mock_send_mail):
        mock_send_mail.return_value = True
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):
            self.mock_transbank_response_error()
            self.assertRaises(
                GatewayError, self.processor.commit_transaction, "token")

    def test_boleta_emission_disabled(self):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS_DISABLED):
            self.processor.boleta_emission(
                self.basket, create_order(basket=self.basket))

    @patch("django.core.mail.send_mail")
    @patch("ecommerce.extensions.payment.boleta.authenticate_boleta_electronica")
    def test_boleta_emission_fail_connection_auth(self, mock_send_mail, mock_auth):
        mock_send_mail.return_value = True

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):

            # Create order and make boleta
            order = create_order(basket=self.basket)

            mock_auth.side_effect = requests.exceptions.ConnectTimeout

            self.assertRaises(Exception,
                              self.processor.boleta_emission, self.basket, order)

    @patch("django.core.mail.send_mail")
    @patch("ecommerce.extensions.payment.boleta.authenticate_boleta_electronica")
    @patch("ecommerce.extensions.payment.boleta.make_boleta_electronica")
    def test_boleta_emission_fail_connection_post(self, mock_send_mail, mock_auth, mock_boleta):
        mock_send_mail.return_value = True

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):

            # Create order and make boleta
            order = create_order(basket=self.basket)

            mock_auth.return_value = True
            mock_boleta.side_effect = requests.exceptions.ConnectTimeout

            self.assertRaises(Exception,
                              self.processor.boleta_emission, self.basket, order)

    @patch("django.core.mail.send_mail")
    @patch("ecommerce.extensions.payment.boleta.authenticate_boleta_electronica")
    @patch("ecommerce.extensions.payment.boleta.make_boleta_electronica")
    def test_boleta_emission_fail_boleta_API(self, mock_send_mail, mock_auth, mock_boleta):
        mock_send_mail.return_value = True

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):

            # Create order and make boleta
            order = create_order(basket=self.basket)

            mock_auth.return_value = True
            mock_boleta.side_effect = BoletaElectronicaException

            # Error creates error description message
            error = BoletaErrorMessage(
                content="Error test", order_number=order.number, error_at="boleta")

            self.assertRaises(Exception,
                              self.processor.boleta_emission, self.basket, order)

    @patch("django.core.mail.send_mail")
    @patch("ecommerce.extensions.payment.boleta.authenticate_boleta_electronica")
    @patch("ecommerce.extensions.payment.boleta.make_boleta_electronica")
    def test_boleta_emission_fail_unkown_error(self, mock_send_mail, mock_auth, mock_boleta):
        mock_send_mail.return_value = True

        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS):

            # Create order and make boleta
            order = create_order(basket=self.basket)

            mock_auth.return_value = True
            mock_boleta.side_effect = Exception

            self.assertRaises(Exception,
                              self.processor.boleta_emission, self.basket, order)

    def test_issue_credit(self):
        self.assertRaises(
            NotImplementedError, self.processor.issue_credit, None, None, None, 0, 'CLP')

    def test_issue_credit_error(self):
        self.assertRaises(
            NotImplementedError, self.processor.issue_credit, None, None, None, 0, 'CLP')
