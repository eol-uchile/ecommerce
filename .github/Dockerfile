FROM ghcr.io/eol-uchile/ecommerce:redwood

# Setup es_CL locales
RUN locale-gen es_CL.UTF-8

# Copy EOL settings
ADD ./.github/eol.py /edx/app/ecommerce/ecommerce/ecommerce/settings/eol.py
ADD ./.github/assets.py /edx/app/ecommerce/ecommerce/ecommerce/settings/assets.py

# Install whitenoise framework to serve assets
RUN pip3 install whitenoise[brotli]

# Make themes and static
ENV DJANGO_SETTINGS_MODULE=ecommerce.settings.assets
ENV DJANGO_ENV=django32
ENV PYTHON_ENV=py38
ENV PYTHON_VERSION=3.8
RUN make clean_static
RUN echo whitenoise[brotli] >> requirements/test.txt
RUN make static
ENV DJANGO_SETTINGS_MODULE=ecommerce.settings.eol

CMD gunicorn --name ecommerce --bind=0.0.0.0:18130 --max-requests=1000 --workers ${WORKER_COUNT:-1} ecommerce.wsgi:application
