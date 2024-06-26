edX E-Commerce Service  |Travis|_ |Codecov|_
============================================
.. |Travis| image:: https://travis-ci.com/edx/ecommerce.svg?branch=master
.. _Travis: https://travis-ci.com/edx/ecommerce

.. |Codecov| image:: http://codecov.io/github/edx/ecommerce/coverage.svg?branch=master
.. _Codecov: http://codecov.io/github/edx/ecommerce?branch=master

This repository contains the edX E-Commerce Service, which relies heavily on `django-oscar <https://django-oscar.readthedocs.org/en/latest/>`_, as well as all frontend and backend code used to manage edX's product catalog and handle orders for those products.

EOL
--------------
Changelog

- changed models on courses/models to add spanish default translations via backend, instead of at frontend runtime.
- added webpay payment processor and views
- changed default error pages for 404 and 500 errors
- added models on extensions/payment
- changed ReceiptResponseView on ecommerce/extensions/checkout/views to add boleta to template context
- added template, javascript and emails
- added commands to extensions/payment
- added mixins to extensions/payment/processors and extensions/payment/views
- modified paypal on extensions/payment to convert from the defaul currency to USD. Also added logic to connect to boleta.

For more details check the .github folder for Installing and on developper notes.

Documentation
-------------

`Documentation <https://edx-ecommerce.readthedocs.io/en/latest/>`_ is hosted on Read the Docs. The source is hosted in this repo's `docs <https://github.com/edx/ecommerce/tree/master/docs>`_ directory. To contribute, please open a PR against this repo.

License
-------

The code in this repository is licensed under version 3 of the AGPL unless otherwise noted. Please see the LICENSE_ file for details.

.. _LICENSE: https://github.com/edx/ecommerce/blob/master/LICENSE

How To Contribute
-----------------

Contributions are welcome. Please read `How To Contribute <https://github.com/edx/edx-platform/blob/master/CONTRIBUTING.rst>`_ for details. Even though it was written with ``edx-platform`` in mind, these guidelines should be followed for Open edX code in general.

Reporting Security Issues
-------------------------

Please do not report security issues in public. Please email security@edx.org.

Get Help
--------

Ask questions and discuss this project on `Slack <https://openedx.slack.com/messages/ecommerce/>`_ or in the `edx-code Google Group <https://groups.google.com/forum/#!forum/edx-code>`_.
