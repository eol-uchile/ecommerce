# Integration Help

## Installation, Config, Commands and reasons

### Initial configuration
```
python manage.py create_or_update_site \
  --site-id=1 \
  --site-name=ecommerce.staging.eol.espinoza.dev
  --site-domain=ecommerce.staging.eol.espinoza.dev \
  --partner-code=eol --partner-name='Eol edX' \
  --lms-url-root=staging.eol.espinoza.dev \
  --payment-processors=webpay \
  --backend-service-client-id=CHANGE ME \
  --backend-service-client-secret=CHANGE ME \
  --sso-client-id=CHANGE ME \
  --sso-client-secret=CHANGE ME \
  --from-email=eol-ayuda@uchile.cl \
  --payment-support-email=eol-ayuda@uchile.cl \
  --payment-support-url=https://eol.uchile.cl/faq \
  --discovery_api_url=https://discovery.staging.eol.espinoza.dev/api/v1 \
  --base-cookie-domain .staging.eol.espinoza.dev
```

The partner code is used to define the payment processor configuration. The default code normally is edx.

### Getting into the admin console

The Oauth login should add the is_staff flag to provide access to the Oscar web interface.
If access to the Django Admin is still forbidden a simple 
```python manage.py createsuperuser```
will add an admin user, but the catch is that by default the service expects a valid lms_user_id to be set.
You can add it manually by using the django shell
```python 
from django.contrib.auth import get_user_model

User = get_user_model()
my_user = User.objects.filter(email="your@email.com")[0] # or use username
my_user.lms_user_id = VALID_NUMBER
my_user.save()
```
This will give you access :)

### Using the Admin

Some values that should be lookep upon in case of malfunctions:
- Base cookie domain
- Discovery API URL: for example https://discovery.staging.eol.espinoza.dev/api/v1
- Payment support url: https://eol.uchile.cl/faq
- Payment support email: eol-ayuda@uchile.cl

**ADD on the Ecommerce admin** on the *django wafle / switches* a new switch with the name payment_processor_active_webpay and set it as active 

## LMS

Create a user for the ecommerce service that can provide access using oauth2.
Then configure the credentials on application oauth Toolkit / Applications :
  - client id: any
  - user: the ecommerce service user id
  - client type: confidential
  - authorization grant type: client credentials, as the ecommerce service uses the deprecated edx-rest-api code.
  - client secret: any
  - name: descriptive name
  - skip authorization: true or checked

Add a second application for the oauth grants:
  - client id: any
  - user: empty
  - redirect urls: https://ecommerce.staging.eol.espinoza.dev/complete/edx-oauth2/
  - client type: Confidential
  - authorization grant type: authorization code
  - client secret: any
  - name: descriptive name
  - skip authorization: true or checked

These configuration must match first the BACKEND_SERVICE_EDX keys and for the latter the SOCIAL_AUTH_EDX_OAUTH2


Afterwards add the *commerce/commerce configurations* with the defaults and a time of 60 seconds.

Finally add the scopes *user_id, profile, email* to the application grants and associate it to the oauth application with authorization code.

## Other references

[Install docs](https://github.com/edx/ecommerce/blob/5a3f18f91f36c7af461bfd52e7c21578c62d4912/docs/install_ecommerce.rst#configure-oauth)