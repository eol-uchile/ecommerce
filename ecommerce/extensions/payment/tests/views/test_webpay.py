from decimal import Decimal

import json
import mock
import ddt
import responses
import httpretty
from django.test.client import RequestFactory
from django.urls import reverse
from django.test import override_settings
from oscar.core.loading import get_model
from testfixtures import LogCapture

from ecommerce.core.constants import (
    ENROLLMENT_CODE_PRODUCT_CLASS_NAME,
    ENROLLMENT_CODE_SWITCH,
    SEAT_PRODUCT_CLASS_NAME
)
from ecommerce.core.models import BusinessClient, SiteConfiguration
from ecommerce.core.tests import toggle_switch
from ecommerce.courses.tests.factories import CourseFactory
from ecommerce.extensions.basket.constants import PURCHASER_BEHALF_ATTRIBUTE
from ecommerce.extensions.basket.utils import basket_add_organization_attribute
from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.extensions.offer.constants import DYNAMIC_DISCOUNT_FLAG
from ecommerce.extensions.offer.tests.test_dynamic_conditional_offer import _mock_jwt_decode_handler
from ecommerce.extensions.payment.processors.webpay import Webpay, WebpayAlreadyProcessed, WebpayRefundRequired, WebpayTransactionDeclined
from ecommerce.extensions.payment.tests.mixins import BoletaMixin, TransbankMixin
from ecommerce.extensions.payment.views.webpay import WebpayPaymentNotificationView, WebpayErrorView
from ecommerce.extensions.test.factories import create_basket, create_order
from ecommerce.invoice.models import Invoice
from ecommerce.tests.factories import UserFactory
from ecommerce.tests.testcases import TestCase

ProductClass = get_model('catalogue', 'ProductClass')
PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')


@ddt.ddt
class WebpayExecutionViewTests(TransbankMixin, BoletaMixin, TestCase):
    path = reverse('webpay:execute')

    def setUp(self):
        super(WebpayExecutionViewTests, self).setUp()
        self.price = '100.0'
        self.user = self.create_user()
        #self.client.login(username=self.user.username, password=self.password)
        self.seat_product_class, __ = ProductClass.objects.get_or_create(
            name=SEAT_PRODUCT_CLASS_NAME)
        self.basket = create_basket(
            owner=self.user, site=self.site, price=self.price, product_class=self.seat_product_class
        )
        self.basket.freeze()

        self.processor = Webpay(self.site)
        self.processor_name = self.processor.NAME

        self.data = {"token_ws": "token"}

    def create_initial_processor_response(self):
        webpay_response = {"token": "test-token", "url": "http://webpay.cl"}
        self.processor.record_processor_response(
            webpay_response, transaction_id=self.basket.order_number, basket=self.basket)

    def test_post_no_token(self):
        response = self.client.post(self.path)
        self.assertTemplateUsed(response, "402.html")
        self.assertContains(
            response, "Hubo un error al obtener los detalles desde Webpay.", status_code=402)

    def test_post_no_response(self):
        response = self.client.post(self.path, self.data)
        self.assertTemplateUsed(response, "402.html")
        self.assertContains(
            response, "Hubo un error al obtener los detalles desde Webpay.", status_code=402)

    @responses.activate
    def test_post_no_basket(self):
        self.mock_transbank_status_response(
            status='INITIALIZED',
            amount=float(self.basket.total_incl_tax),
            order=self.basket.order_number,
            response_code=0)
        self.create_initial_processor_response()
        self.basket.delete()
        response = self.client.post(self.path, self.data)
        self.assertTemplateUsed(response, "402.html")
        self.assertContains(
            response, "El carrito solicitado no existe.", status_code=402)

    @responses.activate
    def test_post_one_basket_one_processor_response(self):
        self.mock_transbank_status_response(
            status='INITIALIZED',
            amount=float(self.basket.total_incl_tax),
            order=self.basket.order_number,
            response_code=0)
        self.create_initial_processor_response()
        response = self.client.post(self.path, self.data)
        self.assertTemplateUsed(response, "402.html")
        self.assertContains(
            response, "Hubo un error al procesar el carrito. Guarde su número de orden", status_code=402)

    @responses.activate
    def test_post_one_basket_two_processor_responses(self):
        self.mock_transbank_status_response(
            status='INITIALIZED',
            amount=float(self.basket.total_incl_tax),
            order=self.basket.order_number,
            response_code=0)
        # Emulate double processor responses mistery error
        self.create_initial_processor_response()
        self.create_initial_processor_response()
        response = self.client.post(self.path, self.data)
        self.assertTemplateUsed(response, "402.html")
        self.assertContains(
            response, "Hubo un error al procesar el carrito. Guarde su número de orden", status_code=402)

    @httpretty.activate
    @mock.patch.object(WebpayPaymentNotificationView, 'handle_payment', side_effect=WebpayTransactionDeclined(-1))
    def test_post_webpay_commit_error(self, mock_handle_payment):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS_DISABLED):
            self.create_initial_processor_response()
            details = self.get_transaction_details_helper(
                status='INITIALIZED',
                amount=float(self.basket.total_incl_tax),
                order=self.basket.order_number,
                response_code=0)

            httpretty.register_uri(httpretty.POST, "http://transbank:5000/transaction-status",
                                   body=json.dumps(details), content_type='application/json', status=200)

            self.mock_access_token_response()
            self.client.login(username=self.user.username,
                              password=self.password)
            response = self.client.post(self.path, self.data)
            # Since the last method is mocked we just verify that
            # the order completion command has been called
            self.assertEqual(mock_handle_payment.call_count, 1)
            self.assertRedirects(response, "{}?code={}&order={}".format(reverse('webpay:failure'),-1,self.basket.order_number))

    @responses.activate
    @mock.patch.object(WebpayPaymentNotificationView, 'handle_payment', side_effect=WebpayRefundRequired())
    def test_post_webpay_commit_refund_error(self, mock_handle_payment):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS_DISABLED):
            self.create_initial_processor_response()
            self.mock_transbank_status_response(
                status='INITIALIZED',
                amount=float(self.basket.total_incl_tax),
                order=self.basket.order_number,
                response_code=0)

            response = self.client.post(self.path, self.data)
            # Since the last method is mocked we just verify that
            # the order completion command has been called
            self.assertEqual(mock_handle_payment.call_count, 1)
            self.assertTemplateUsed(response, "402.html")
            self.assertContains(
                response, "Hubo un error desde Webpay.", status_code=402)

    @responses.activate
    @mock.patch.object(WebpayPaymentNotificationView, 'handle_payment', side_effect=WebpayAlreadyProcessed())
    def test_post_webpay_commit_repeated_error(self, mock_handle_payment):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS_DISABLED):
            self.create_initial_processor_response()
            self.mock_transbank_status_response(
                status='INITIALIZED',
                amount=float(self.basket.total_incl_tax),
                order=self.basket.order_number,
                response_code=0)

            response = self.client.post(self.path, self.data)
            # Since the last method is mocked we just verify that
            # the order completion command has been called
            self.assertEqual(mock_handle_payment.call_count, 1)
            self.assertTemplateUsed(response, "402.html")
            self.assertContains(
                response, "El pago ya registra como procesado en ecommerce.", status_code=402)

    @responses.activate
    @mock.patch.object(WebpayPaymentNotificationView, 'handle_payment', side_effect=Exception())
    def test_post_webpay_commit_repeated_error(self, mock_handle_payment):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS_DISABLED):
            self.create_initial_processor_response()
            self.mock_transbank_status_response(
                status='INITIALIZED',
                amount=float(self.basket.total_incl_tax),
                order=self.basket.order_number,
                response_code=0)

            response = self.client.post(self.path, self.data)
            # Since the last method is mocked we just verify that
            # the order completion command has been called
            self.assertEqual(mock_handle_payment.call_count, 1)
            self.assertTemplateUsed(response, "402.html")
            self.assertContains(
                response, "Hubo un error al procesar el carrito.", status_code=402)

    @responses.activate
    @mock.patch.object(WebpayPaymentNotificationView, 'handle_post_order')
    @mock.patch.object(WebpayPaymentNotificationView, 'handle_order_placement')
    def test_post_happy_path(self, mock_post_order, mock_handle_order):
        with override_settings(BOLETA_CONFIG=self.BOLETA_SETTINGS_DISABLED):
            self.create_initial_processor_response()
            self.mock_transbank_status_response(
                status='INITIALIZED',
                amount=float(self.basket.total_incl_tax),
                order=self.basket.order_number,
                response_code=0)
            self.mock_transbank_response(
                status='AUTHORIZED',
                amount=float(self.basket.total_incl_tax),
                order=self.basket.order_number,
                response_code=0)
            mock_post_order.return_value = True
            mock_handle_order.return_value = True
            self.client.login(username=self.user.username,
                              password=self.password)
            response = self.client.post(self.path, self.data)
            # Since the last method is mocked we just verify that
            # the order completion command has been called
            self.assertEqual(mock_handle_order.call_count, 1)
            self.assertEqual(mock_post_order.call_count, 1)


@ddt.ddt
class WebpayErrorViewTests(TestCase):
    path = reverse('webpay:failure')

    def setUp(self):
        super(WebpayErrorViewTests, self).setUp()
        self.user = self.create_user()

    @ddt.data(
        {'code': -1, 'order': 'order'},
        {'code': -2, 'order': 'order'},
        {'code': -3, 'order': 'order'},
        {'code': -4, 'order': 'order'},
        {'code': -100, 'order': 'order'},
    )
    @httpretty.activate
    def test_post_webpay_commit_error(self, data):
        self.mock_access_token_response()
        self.client.login(username=self.user.username, password=self.password)
        response = self.client.get(self.path, data)
        # Since the last method is mocked we just verify that
        # the order completion command has been called
        self.assertTemplateUsed(response, "edx/checkout/webpay_error.html")
