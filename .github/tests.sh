#!/usr/bin/env bash

tox -e py38-django22-tests ecommerce/extensions/payment/tests/processors/test_webpay.py
tox -e py38-django22-tests ecommerce/extensions/payment/tests/test_boleta.py
tox -e py38-django22-tests ecommerce/extensions/payment/management/tests/test_boleta_emissions.py
