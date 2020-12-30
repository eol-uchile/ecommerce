import requests
import io
import logging
from base64 import b64encode

from django.http import FileResponse, HttpResponse
from django.shortcuts import render
from django.conf import settings
from django.core.mail import send_mail
from oscar.core.loading import get_model
from ecommerce.extensions.payment.models import UserBillingInfo, BoletaElectronica

logger = logging.getLogger(__name__)
Order = get_model('order','Order')
default_config = {
    "enabled": False,
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

def make_paragraphs_200(line):
    """
    Create paragraphs of 200 characters (including \ n)
    """
    if len(line) > 200:
        # Max line is 1000 in length
        # Consider 4 ^ chars
        remainder = line[:996]
        iterate = len(remainder)//200
        newline = ""
        for i in range(0,iterate):
            newline = newline + remainder[:199] + "^"
            remainder = remainder[199:]
        # final without ^
        newline = newline+remainder
        return newline
    else:
        return line

def authenticate_boleta_electronica(configuration=default_config):
    """
    Recover boleta electronica authorization tokens
    given a valid Webpay configuration object

    Arguments:
        configuration - settings with keys, scopes, etc

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
    try:
        result = requests.post(config_ventas_url + '/authorization-token', headers=header, data={
            'grant_type': "client_credentials",
            'scope': client_scope
        })
        result.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise BoletaElectronicaException("http error "+str(e))
    return result.json()


def make_boleta_electronica(basket, order_total, auth, configuration=default_config):
    """
    Recover billing information and create a new boleta
    from the UChile API. Finally register info to BoletaElectronica

    Arguments:
      basket - basket with line(and products) info, owner(user)
      order_total - total payed by client
      auth - authorization response from the UChile API
      configuration - configuration file from a webpay payment processor
    Returns:
      It returns the id of the new boleta
    """

    # Get user info
    billing_info = UserBillingInfo.objects.get(basket=basket)
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
    courseTitle = course_product.title.replace('Seat in ','')
    courseTitle = courseTitle[:courseTitle.find(" with ")]

    itemName = "Certificado: curso de formación en extensión"

    # Limit lengths
    itemDescription = make_paragraphs_200("Curso: {}".format(courseTitle))

    # TODO: Sacar todo lo que creemos que es opcional, y hacer busqueda binaria
    data = {
        "datosBoleta": {
            "afecta": False, # No afecto a impuestos
            "detalleProductosServicios": [{
                "cantidadItem": product_lines[0].quantity,
                #"centroCosto": configuration["config_centro_costos"],
                "cuentaContable": configuration["config_cuenta_contable"],
                "descripcionAdicionalItem": itemDescription,
                "identificadorProducto": course_product.id,
                "impuesto": 0.0,
                "indicadorExencion": 2,  # Servicio no facturable
                "nombreItem": itemName,
                "precioUnitarioItem": product_lines[0].price_incl_tax,
                "unidadMedidaItem": "",
            }],
            "indicadorServicio": 3,  # Boletas de venta y servicios
            "receptor": {
                "apellidoPaterno": billing_info.last_name_1[:12],
                "apellidoMaterno": billing_info.last_name_2[:12],
                "nombre": billing_info.first_name[:12],
                "rut": rut,
            },
            "referencia": [{  # Opcional para gestion interna
                "codigoCaja": "eceol",
                "codigoReferencia": basket.order_number, # Max length 18
                "codigoVendedor": "INTERNET",
                "razonReferencia": "Orden de compra: "+str(course_product.id), # Max length 90
            }, ],
            "saldoAnterior": 0,
        },
        "puntoVenta": {
            "cuentaCorriente": True,  # Se requiere para anular la venta
            "identificadorPos": configuration["config_identificador_pos"],
            "sucursal": {  # Opcional
                "codigo": auth["codigoSII"], #configuration["config_sucursal"],
                "comuna": "Santiago",
                "direccion": "Diagonal Paraguay Nº 257",
                "reparticion": auth["repCodigo"], #configuration["config_reparticion"],
            },
        },
        "recaudaciones": [{
            "monto": order_total,
            "tipoPago": "Tarjeta de Crédito",  # Efectivo | Debito | Tarjeta de Crédito
            "voucher": basket.order_number, # numero para gestion interna de transacciones
        }],
    }

    # Opcional en nuestro caso (Servicio 3) aplica para comuna, direccion, ciudad
    if billing_info.billing_country_iso2 == "CL":
        data["datosBoleta"]["receptor"]["ciudad"] = billing_info.billing_city[:20]
        data["datosBoleta"]["receptor"]["comuna"] = billing_info.billing_district[:20]
        data["datosBoleta"]["receptor"]["direccion"] = billing_info.billing_address[:70]

    try:
        result = requests.post(config_ventas_url + "/ventas",
                               headers=header,
                               json=data,
                               )
        if ("folio" in result.text) and ("no" in result.text):
            raise BoletaSinFoliosException()
        result.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise BoletaElectronicaException("http error "+str(e))
    except BoletaSinFoliosException:
        # Panic and Send mail 
        send_mail(
            'Boleta Electronica API Fatal Error',
            'No quedan mas folios para la API de boletas electronicas. Panic!', None, ['ing-eol@uchile.cl'],
            fail_silently=False,
        )
        raise BoletaElectronicaException("no more folios")

    voucher_id = result.json()['id']
    voucher_url = '{}/ventas/{}/boletas/pdf'.format(
        config_ventas_url, voucher_id)

    boleta = BoletaElectronica(
        basket=basket, receipt_url=voucher_url, voucher_id=voucher_id)
    boleta.save()

    billing_info.boleta = boleta
    billing_info.save()

    return {
        'id': voucher_id,
        'receipt_url':  voucher_url
    }


# VIEWS
def recover_boleta(request, configuration=default_config):
    """
    Recover boleta PDF from UChile API given the order_number on
    the get params
    """
    # Error context
    context = {
        "order_number": "",
        "msg": "Hubo un error al recuperar su boleta electrónica.",
        "payment_support_email": request.site.siteconfiguration.payment_support_email
    }

    if not request.user.is_authenticated:
        context['msg'] = '¡Debe estar autenticado en el sistema!.'
        return render(request, "edx/checkout/boleta_error.html",context)
        
    user_id = request.user.id

    # Recover boleta info
    if 'order_number' in request.GET:
        order_number = request.GET['order_number']
    else:
        logger.error("No Order provided to recover_boleta")
        context['msg'] = '¡Debe proveer un número de orden!.'
        return render(request, "edx/checkout/boleta_error.html",context)

    context["order_number"] = order_number

    try:
        order = Order.objects.get(number=order_number)
        boleta = BoletaElectronica.objects.get(basket=order.basket)
        if boleta.basket.owner.id != user_id:
            logger.error("User does not own the Basket provided to recover_boleta")
            context['msg'] = 'El usuario no es dueño de la orden solicitada.'
            return render(request, "edx/checkout/boleta_error.html",context)
    
        # Create buffer and populate
        boleta_auth = authenticate_boleta_electronica(configuration)
        config_ventas_url = configuration["config_ventas_url"]
        file = requests.get(config_ventas_url + '/ventas/{}/boletas/pdf'.format(boleta.voucher_id),
                        headers={"Authorization": "Bearer " +
                                 boleta_auth["access_token"]}
                        )
        buffer = io.BytesIO(file.content)
        pdfName = 'boleta-{}.pdf'.format(boleta.voucher_id)

        return FileResponse(buffer, as_attachment=True, filename=pdfName)
    except Order.DoesNotExist:
        logger.error("Order does not exists, number: "+str(order_number))
        context['msg'] = 'La orden solicitada no existe.'
        return render(request, "edx/checkout/boleta_error.html",context)
    except BoletaElectronica.DoesNotExist:
        logger.error("Boleta Electronica does not exists, number: "+str(order_number))
        context['msg'] = 'La boleta solicitada no existe.'
        return render(request, "edx/checkout/boleta_error.html",context)
    except BoletaElectronicaException as e:
        logger.error("Error while getting Boleta Electronica PDF, "+e, exc_info=True)
        return render(request, "edx/checkout/boleta_error.html",context)
    except requests.exceptions.ConnectionError as e:
        logger.error("Error while getting Boleta Electronica PDF, "+e, exc_info=True)
        return render(request, "edx/checkout/boleta_error.html",context)
    except Exception as e:
        logger.error("Error while getting Boleta Electronica PDF, "+e, exc_info=True)
        return render(request, "edx/checkout/boleta_error.html",context)