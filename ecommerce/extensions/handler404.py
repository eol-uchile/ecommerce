import logging
from urllib.parse import quote

from django.http import HttpResponse
from django.template import TemplateDoesNotExist, loader
from django.views.defaults import page_not_found

from ecommerce.core.url_utils import _get_site_configuration

logger = logging.getLogger(__name__)

ERROR_402_TEMPLATE_NAME = "402.html"

class HttpResponsePaymentError(HttpResponse):
  status_code = 402

def handler404(request, exception):  # pylint: disable=unused-argument
    """
    404 handler.

    If the error comes from a /payment/*processor*/execute then it is the
    result of a catastrophic error and a different error must appear.

    Templates: :template:`404.html` and `402.html`
    Context:
        request_path
            The path of the requested URL (e.g., '/app/pages/bad_page/'). It's
            quoted to prevent a content injection attack.
        exception
            The message from the exception which triggered the 404 (if one was
            supplied), or the exception class name
    """

    if "/execute/" in request.get_full_path():
        
        exception_repr = exception.__class__.__name__
        message = "error"
        try:
            message = exception.args[0]
        except (AttributeError, IndexError):
            pass
        else:
            if isinstance(message, str):
                exception_repr = message

        siteC = _get_site_configuration()
        
        context = {
            'request_path': quote(request.path),
            'exception': exception_repr,
            'support_email': siteC.payment_support_email
        }
        try:
            template = loader.get_template(ERROR_402_TEMPLATE_NAME)
            body = template.render(context, request)
            content_type = None             # Django will use DEFAULT_CONTENT_TYPE
        except TemplateDoesNotExist:
            # Fall back to default 404 error
            logger.error("402 template not found!")
            return page_not_found(request, exception)
        return HttpResponsePaymentError(body, content_type=content_type)

    return page_not_found(request, exception)