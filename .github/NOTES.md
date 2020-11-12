# Notes during development

## Webpay

Webpay was added as a payment processor on the files *ecommerce/settings/_oscar.py* and it should be added to the partner (a partner is the short_code added on the admin interface) configuration in PAYMENT_PROCESSOR_CONFIG with the following variables:
  * api_url
  * api_secret

For example on your yml file:
```
PAYMENT_PROCESSOR_CONFIG:
  edx:
    paypal:
    ...
  eol:
    webpay:
      api_url: http://transbank:5000
      api_secret: my-secret-is-really-important
```
You can always configure your partner with the short code edx and just add the webpay config file under that dictionary.

## Reference for configuration

Check this link to configure the variables between the lms and the ecommerce service
[test ecommerce doc](https://github.com/edx/ecommerce/blob/5a3f18f91f36c7af461bfd52e7c21578c62d4912/docs/test_ecommerce.rst)