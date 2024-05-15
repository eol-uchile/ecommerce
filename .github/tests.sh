#!/usr/bin/env bash

set -e

tox -e py38-django22-tests \
 ecommerce/extensions/payment/tests/processors/test_webpay.py \
 ecommerce/extensions/payment/tests/processors/test_paypal.py \
 ecommerce/extensions/payment/tests/views/test_webpay.py \
 ecommerce/extensions/payment/tests/views/test_paypal.py \
 ecommerce/extensions/payment/tests/test_boleta.py \
 ecommerce/extensions/payment/management/tests/test_boleta_emissions.py \
 ecommerce/extensions/payment/management/tests/test_fulfill_order.py \
 ecommerce/extensions/payment/management/tests/test_complete_boleta.py \
 ecommerce/extensions/payment/management/tests/test_get_boleta_emissions.py
