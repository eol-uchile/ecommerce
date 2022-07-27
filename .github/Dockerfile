FROM ubuntu:20.04

# Install system requirements
RUN apt update && \
    apt install -y --no-install-recommends python3 python3-dev python3-pip python3-setuptools libmysqlclient-dev mysql-client git make build-essential gcc locales \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --upgrade pip

# Setup system locales, this is used to fix accent in code
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8

# Get nodejs
RUN pip install nodeenv
RUN nodeenv /openedx/nodeenv --node=12.13.0 --prebuilt

WORKDIR /openedx/ecommerce
ADD . /openedx/ecommerce
ADD ./.github/eol.py /openedx/ecommerce/ecommerce/settings/eol.py
ADD ./.github/test.py /openedx/ecommerce/ecommerce/settings/test.py
ADD ./.github/assets.py /openedx/ecommerce/ecommerce/settings/assets.py

# Modify email templates
ADD ./.github/email_templates/. /openedx/ecommerce/ecommerce/templates/oscar/customer/

# Copy custom JS and configurations
ADD ./.github/js/build.js /openedx/ecommerce/build.js
ADD ./.github/js/config.js /openedx/ecommerce/ecommerce/static/js/config.js
ADD ./.github/js/eol_basket_app.js /openedx/ecommerce/ecommerce/static/js/apps/eol_basket_app.js
ADD ./.github/js/basket_page.js /openedx/ecommerce/ecommerce/static/js/eol_pages/basket_page.js
ADD ./.github/js/rut_validator.js /openedx/ecommerce/ecommerce/static/js/utils/rut_validator.js
ADD ./.github/js/offer_view.js /openedx/ecommerce/ecommerce/static/js/views/offer_view.js

# Make requirements, Themes and static
ADD ./.github/themes/. /openedx/ecommerce/ecommerce/themes/
ENV PATH /openedx/nodeenv/bin:${PATH}
RUN make production-requirements
RUN pip3 install python-json-logger==0.1.11 whitenoise==5.2.0
RUN DJANGO_SETTINGS_MODULE=ecommerce.settings.assets make static

# Copy EOL scripts
ADD ./.github/tests.sh /openedx/ecommerce/tests.sh
ADD ./.github/verify_and_do_boletas.sh /openedx/ecommerce/verify_and_do_boletas.sh

EXPOSE 8000
ENV DJANGO_SETTINGS_MODULE=ecommerce.settings.eol
CMD gunicorn --name ecommerce --bind=0.0.0.0:8000 --max-requests=1000 --workers ${WORKER_COUNT:-1} ecommerce.wsgi:application
