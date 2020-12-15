# Notes during development

## Themming and adding custom Javascript Applications

When loading custom JS code for templates it may not load or compile. The troubleshoot procedure is to:
1. Check if the file is imported directly by the template. It may be imported as a required module from another JS file.
2. Check if the file needs to be compiled
    - If it does then modify the files:
      - build.js
      - ecommerce/static/js/config.js
    - The latter tell ```r3.js``` to where look for and what to compile.
3. ```make static``` by rebuilding the image. Whitenoise seems not to update the references, which may result on the app not loading the new files.

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