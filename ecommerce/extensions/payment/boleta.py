import io
import json
import logging
from base64 import b64encode
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import requests
import waffle
from django.conf import settings
from django.core.cache import cache
from django.http import FileResponse, HttpResponse, Http404
from django.shortcuts import render
from oscar.core.loading import get_model

from ecommerce.core.url_utils import (
    get_lms_dashboard_url,
    get_lms_explore_courses_url,
)

from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.extensions.payment.models import BoletaElectronica, BoletaErrorMessage, UserBillingInfo, BoletaUSDConversion
from ecommerce.notifications.notifications import send_notification

logger = logging.getLogger(__name__)
Order = get_model('order', 'Order')
default_config = {
    "enabled": False,
    "generate_on_payment": False,
    "send_boleta_email": False,
    "client_id": "secret",
    "client_secret": "secret",
    "client_scope": "dte:tdo",
    "config_centro_costos": "secret",
    "config_cuenta_contable": "secret",
    "config_sucursal": "secret",
    "config_reparticion": "secret",
    "config_identificador_pos": "secret",
    "config_ventas_url": "https://ventas-test.uchile.cl/ventas-api-front/api/v1",
}
if hasattr(settings, 'BOLETA_CONFIG'):
    default_config = settings.BOLETA_CONFIG


class BoletaElectronicaException(Exception):
    """Raised when the UChile API returns an error"""

    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return "BOLETA API Error: {}".format(self.msg)


class BoletaSinFoliosException(Exception):
    """Raised when the UChile API has no more tickets"""

    def __str__(self):
        return "BOLETA API Error: no hay mas folios"


def make_paragraphs_200(line, order_number):
    """
    Create paragraphs of 200 characters (including \ n)
    and append a new line with the order_number
    """
    len_order = len(order_number)
    append_order_number = "^"+order_number

    if len(line) > 200:
        # Max line is 1000 in length
        # We'll use 4 lines for product description and the final line
        # will contain the order_number
        # Consider 4 ^ chars
        remainder = line[:796]
        iterate = len(remainder)//200
        newline = ""
        for i in range(0, iterate):
            newline = newline + remainder[:199] + "^"
            remainder = remainder[199:]
        # final without ^
        newline = newline+remainder+append_order_number
        return newline
    else:
        return line+append_order_number


def authenticate_boleta_electronica(configuration=default_config, basket=None):
    """
    Recover boleta electronica authorization tokens
    given a valid Webpay configuration object

    Arguments:
        configuration - settings with keys, scopes, etc
        basket - Basket object for correct error message setting, if none
                is provided the error won't associate any order-number

    Returns:
      Credentials response with token
    """
    client_id = configuration["client_id"]
    client_secret = configuration["client_secret"]
    config_ventas_url = configuration["config_ventas_url"]
    client_scope = configuration["client_scope"]

    header = {
        'Authorization': 'Basic ' + b64encode("{}:{}".format(client_id, client_secret).encode()).decode()
    }
    error_response = None
    try:
        result = requests.post(config_ventas_url + '/authorization-token', headers=header, data={
            'grant_type': "client_credentials",
            'scope': client_scope
        })
        error_response = result
        result.raise_for_status()
    except requests.exceptions.HTTPError as e:
        error_text = error_response.text
        try:
            error_text = json.dumps(error_response.json(), indent=1)
        except Exception:
            pass
        order_number = "unset"
        if basket is not None:
            order_number = basket.order_number
        boleta_error_message = BoletaErrorMessage(
            content=error_text[:255],
            code=error_response.status_code,
            order_number=order_number)
        boleta_error_message.save()
        raise BoletaElectronicaException("http error "+str(e))
    return result.json()


def send_boleta_email(basket):
    """
    Send notification signal to ecommerce/notifications/notifications.py
    to send boleta notification template with code BOLETA_READY
    """
    try:
        order = Order.objects.get(basket=basket)

        product = order.lines.first().product
        receipt_page_url = get_receipt_page_url(
            order_number=order.number,
            site_configuration=order.site.siteconfiguration
        )
        recipient = order.user.email

        send_notification(
            order.user,
            'BOLETA_READY',
            {
                'course_title': product.title,
                'receipt_page_url': receipt_page_url,
            },
            order.site,
            recipient
        )
    except Exception:
        logger.error("Couldn't send boleta email notification")


def raise_boleta_error(response, e, create_error=False, order=None):
    """
    Save response for email alarms.
    The webprocessor or the management command will consume it

    Raises BoletaElectronicaException
    """
    error_text = response.text
    try:
        error_text = json.dumps(response.json(), indent=1)
    except Exception:
        pass
    if create_error:
        boleta_error_message = BoletaErrorMessage(
            content=error_text[:255],
            code=response.status_code,
            order_number=order)
        boleta_error_message.save()
    raise BoletaElectronicaException("http error "+str(e))


def determine_billable_price(basket, product_line, order, payment_processor='webpay'):
    """
    Determine billable price considering discounts
    and if the sale was done with USD instead of CLP
    """
    if payment_processor == 'paypal':
        # Determine price sent to paypal
        conversion_rate_used = basket.paypalusdconversion_set.first().clp_to_usd
        dollars = (Decimal(product_line.unit_price_incl_tax) / Decimal(conversion_rate_used)).quantize(Decimal('.11'), rounding=ROUND_HALF_UP)

        # Parse to the current billable price
        billable_conversion_rate = BoletaUSDConversion.objects.first().clp_to_usd
        total = (Decimal(dollars) * Decimal(billable_conversion_rate) * Decimal(product_line.quantity)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        total = int(total)
        
        unitPrice = (Decimal(dollars) * Decimal(billable_conversion_rate)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        unitPrice = int(unitPrice)
        return unitPrice, total
    else:
        # DISCLAIMER:
        # Currently discounts can only be between 1-99% of price
        # and only applied when purchasing a SINGLE PRODUCT.
        # Get price if discount is applied
        # NOTE: this is redundant but later we might need it
        unitPrice = product_line.unit_price_incl_tax
        if order.total_discount_incl_tax != 0 and product_line.quantity == 1:
            unitPrice = order.total_incl_tax

        return unitPrice, order.total_incl_tax

def associate_boleta_to_conversion(boleta, payment_processor='webpay'):
    if payment_processor == 'paypal':
        billable_conversion_rate = BoletaUSDConversion.objects.first()
        billable_conversion_rate.boleta.add(boleta)
        billable_conversion_rate.save()


def make_boleta_electronica(basket, order, auth, configuration=default_config, payment_processor='webpay'):
    """
    Recover billing information and create a new boleta
    from the UChile API. Finally register info to BoletaElectronica

    Arguments:
      basket - basket with line(and products) info, owner(user)
      order - completed order
      auth - authorization response from the UChile API
      configuration - configuration file from a webpay payment processor
    Returns:
      It returns the id of the new boleta
      
      Reference within the VPN

      https://ventas-test.uchile.cl/ventas-api-front/api/v1/swagger-ui.html#/ventas-controller/creaVentaUsingPOST
    """

    # Get user info
    billing_info = UserBillingInfo.objects.filter(basket=basket, payment_processor=payment_processor).first()
    rut = billing_info.id_number
    # Rut del Receptor. Si no se informa, por regulación, se agrega 66666666-6. (Largo máximo 10, formato 12345678-K)
    # NOTE: API RUT max length is 10
    if billing_info.id_option != UserBillingInfo.RUT:
        rut = "66666666-6"

    # Get product info
    product_lines = basket.all_lines()
    if len(product_lines) > 1:
        raise Exception(
            "No multiple product implementation for boleta Electronica")
    course_product = product_lines[0].product

    header = {
        "Authorization": "Bearer " + auth["access_token"]
    }
    config_ventas_url = configuration["config_ventas_url"]

    # TODO: Diferenciar si pago con credito o debito
    # Respuestas de Webpay
    # VN es Credito
    # VD es Debito
    # Asume credit
    courseTitle = course_product.title

    itemName = "Certificado: curso de formación en extensión"

    # Limit lengths
    itemDescription = make_paragraphs_200(
        "Curso: {}".format(courseTitle), basket.order_number)

    unitPrice, order_total = determine_billable_price(basket, product_lines[0], order, payment_processor)

    data = {
        "datosBoleta": {
            "afecta": False,  # No afecto a impuestos
            "detalleProductosServicios": [{
                "cantidadItem": product_lines[0].quantity,
                # Uncommented
                "centroCosto": configuration["config_centro_costos"],
                "cuentaContable": configuration["config_cuenta_contable"],
                "descripcionAdicionalItem": itemDescription,
                "identificadorProducto": course_product.id,
                "impuesto": 0.0,
                "indicadorExencion": 2,  # Servicio no facturable
                "nombreItem": itemName,
                "precioUnitarioItem": unitPrice,
                "unidadMedidaItem": "",
            }],
            "indicadorServicio": 3,  # Boletas de venta y servicios
            "receptor": {
                "nombre": billing_info.first_name,
                "apellidoPaterno": billing_info.last_name_1,
                "apellidoMaterno": billing_info.last_name_2,
                "rut": rut,
            },
            "referencia": [{  # Opcional para gestion interna
                "codigoCaja": "eceol",
                "codigoReferencia": basket.order_number,  # Max length 18
                "codigoVendedor": "INTERNET",
                # Max length 90
                "razonReferencia": "Orden de compra: "+str(course_product.id),
            }, ],
            "saldoAnterior": 0,
        },
        "puntoVenta": {
            "cuentaCorriente": True,  # Se requiere para anular la venta
            "identificadorPos": configuration["config_identificador_pos"],
            "sucursal": {  # Opcional
                # auth["codigoSII"],
                "codigo": configuration["config_sucursal"],
                "comuna": "Santiago",
                "direccion": "Diagonal Paraguay Nº 257",
                # auth["repCodigo"],
                "reparticion": configuration["config_reparticion"],
            },
        },
        "recaudaciones": [{
            "monto": order_total,
            "tipoPago": "Tarjeta de Crédito",  # Efectivo | Debito | Tarjeta de Crédito
            "voucher": basket.order_number,  # numero para gestion interna de transacciones
        }],
    }

    # Opcional en nuestro caso (Servicio 3) aplica para comuna, direccion, ciudad
    if billing_info.billing_country_iso2 == "CL":
        data["datosBoleta"]["receptor"]["ciudad"] = billing_info.billing_city[:20]
        data["datosBoleta"]["receptor"]["comuna"] = billing_info.billing_district[:20]
        data["datosBoleta"]["receptor"]["direccion"] = billing_info.billing_address[:70]

    error_response = None
    try:
        result = requests.post(config_ventas_url + "/ventas",
                               headers=header,
                               json=data,
                               )
        error_response = result
        result.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise_boleta_error(error_response, e, True, basket.order_number)

    voucher_id = result.json()['id']
    voucher_url = '{}/ventas/{}/boletas/pdf'.format(
        config_ventas_url, voucher_id)

    boleta = BoletaElectronica(
        basket=basket,
        receipt_url=voucher_url,
        voucher_id=voucher_id,
    )
    boleta.save()

    billing_info.boleta = boleta
    billing_info.save()

    if settings.BOLETA_CONFIG.get("send_boleta_email", False):
        send_boleta_email(basket=basket)

    try:
        boleta_details = get_boleta_details(voucher_id, header)
    except BoletaElectronicaException:
        # Empty details; do not lock and retry later
        logger.warning(
            "Couldn't recover info for boleta {}".format(voucher_id))
        boleta_details = {"boleta": {}, "recaudaciones": [{}]}

    if boleta_details["boleta"].get("fechaEmision", None) == None:
        emission_date = None
    else:
        emission_date = datetime.fromisoformat(
            boleta_details["boleta"]["fechaEmision"])

    boleta.folio = boleta_details["boleta"].get("folio", "")
    boleta.emission_date = emission_date
    boleta.amount = int(boleta_details["recaudaciones"][0].get("monto", 0))
    boleta.save()

    # Save conversion rate if needed
    associate_boleta_to_conversion(boleta, payment_processor)

    return {
        'id': voucher_id,
        'receipt_url':  voucher_url
    }


def get_boleta_details(id, auth_headers, configuration=default_config):
    """
    Recovers boleta data like
    - boleta (folio, timestamp)
    - recaudaciones (amount)
    Returns:
        JSON response
    Raises:
        BoletaElectronicaException
    """
    config_ventas_url = configuration["config_ventas_url"]
    try:
        result = requests.get(
            "{}/ventas/{}".format(config_ventas_url, id),
            headers=auth_headers
        )
        error_response = result
        result.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise_boleta_error(error_response, e)
    return result.json()


def get_boletas(auth_headers, since, state="CONTABILIZADA", configuration=default_config):
    """
    Recovers all boletas since a given date
    Arguments:
    - auth_headers Authorization headers dictionary
    - since a date in ISO format without TZ, i.e. 2020-02-30T00:00:00
    - state one of INGRESADA, SIN_BOLETA, CONTABILIZADA,
    - configuration dictionary
    Returns:
        JSON response
    Raises:
        BoletaElectronicaException
    """
    config_ventas_url = configuration["config_ventas_url"]
    try:
        result = requests.get(
            "{}/ventas/?fecha-desde={}&estado={}".format(
                config_ventas_url, since, state),
            headers=auth_headers
        )
        error_response = result
        result.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise_boleta_error(error_response, e)
    return result.json()

# VIEWS


def recover_boleta(request, configuration=default_config):
    """
    Recover boleta PDF from UChile API given the order_number on
    the get params

    CACHE the Boleta PDF response
    """

    if not hasattr(settings, 'BOLETA_CONFIG') or settings.BOLETA_CONFIG.get('enabled', False) == False:
        raise Http404("Boletas desactivadas para ecommerce")
    # Error context
    context = {
        "order_number": "",
        "msg": "Hubo un error al recuperar su boleta electrónica.",
        "payment_support_email": request.site.siteconfiguration.payment_support_email,
        "order_dashboard_url": get_lms_dashboard_url(),
        "explore_courses_url": get_lms_explore_courses_url(),
    }

    if not request.user.is_authenticated:
        context['msg'] = '¡Debe estar autenticado en el sistema!.'
        return render(request, "edx/checkout/boleta_error.html", context)

    user_id = request.user.id

    # Recover boleta info
    if 'order_number' in request.GET:
        order_number = request.GET['order_number']
    else:
        logger.error("No Order provided to recover_boleta")
        context['msg'] = '¡Debe proveer un número de orden!.'
        return render(request, "edx/checkout/boleta_error.html", context)

    context["order_number"] = order_number

    try:
        boleta = BoletaElectronica.objects.get(
            basket__order__number=order_number)
        if (not request.user.is_superuser) and (boleta.basket.owner.id != user_id):
            logger.error(
                "User does not own the Basket provided to recover_boleta")
            context['msg'] = 'El usuario no es dueño de la orden solicitada.'
            return render(request, "edx/checkout/boleta_error.html", context)

        # Create buffer and populate
        boleta_auth = authenticate_boleta_electronica(configuration)
        config_ventas_url = configuration["config_ventas_url"]

        # Cache the PDF response
        pdf_url = '{}/ventas/{}/boletas/pdf'.format(
            config_ventas_url, boleta.voucher_id)
        file = cache.get(pdf_url)
        if file == None:
            file = requests.get(pdf_url, headers={
                                "Authorization": "Bearer {}".format(boleta_auth["access_token"])})
            file.raise_for_status()
            # Add to cache only if status was OK (no exception on status)
            cache.set(pdf_url, file, 60 *
                      settings.BOLETA_CONFIG.get("pdf_cache", 10))
        buffer = io.BytesIO(file.content)
        pdfName = 'boleta-{}.pdf'.format(boleta.voucher_id)

        return FileResponse(buffer, as_attachment=True, filename=pdfName)
    except BoletaElectronica.DoesNotExist:
        logger.error(
            "Boleta Electronica does not exists, number: "+str(order_number))
        context['msg'] = 'La boleta solicitada no existe.'
        return render(request, "edx/checkout/boleta_error.html", context)
    # also BoletaElectronicaException and requests.exceptions.ConnectionError
    except Exception as e:
        logger.error(
            "Error while getting Boleta Electronica PDF {}".format(e), exc_info=True)
        return render(request, "edx/checkout/boleta_error.html", context)
