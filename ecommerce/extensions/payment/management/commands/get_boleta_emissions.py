import logging
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from oscar.core.loading import get_model, get_class
from oscar.apps.partner import strategy

from ecommerce.extensions.payment.models import BoletaElectronica
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, get_boletas

Order = get_model('order','Order')
Basket = get_model('basket','Basket')

logger = logging.getLogger(__name__)

class Command(BaseCommand):
  help = """Recover boleta's info, counts and verifies that there are no duplicates or inconsistencies"""
  requires_migrations_checks = True

  def add_arguments(self, parser):
    # Optional argument
    parser.add_argument("since", action='store', help="Starting ISO date without TZ")
    parser.add_argument("-s", "--save", action='store_true', help="Save to file")

  def handle(self_true, *args, **options):

    boleta_active = hasattr(settings, 'BOLETA_CONFIG') and settings.BOLETA_CONFIG.get("enabled",False)
    if not boleta_active:
      logger.error("BOLETA_CONFIG is not set or enabled, enable it on your settings to run this commmand")
      return
    
    # Get boletas registry from API
    auth = authenticate_boleta_electronica()
    headers = {
        "Authorization": "Bearer " + auth["access_token"]
    }
    raw_boletas = get_boletas(headers, options["since"])

    if len(raw_boletas) == 0:
      logger.info("No boletas CONTABILIZADAs recovered from Ventas API. Trying state=INGRESADA ...")
      raw_boletas = get_boletas(headers, options["since"], state="INGRESADA")

      if len(raw_boletas) == 0:
        logger.info("No boletas INGRESADAs recovered from Ventas API. Checking local count ...")
        # CHECK ZERO
        # Verify that we don't have any neither
        local_count = BoletaElectronica.objects.filter(emission_date__gte=since).count()

        if local_count == 0:
          logger.info("No Local Boletas. Exiting")
          return
        else:
          logger.error("Inconsistency detected: Local count exists but it has been remotely removed by Ventas API")
          raise CommandError("Inconsistency detected")
        

    # CHECK ONE:
    # Process boletas and review duplicates
    vouchers = {}
    for venta in raw_boletas:
      order_number = venta["recaudaciones"][0]["voucher"]
      vouchers[order_number] = vouchers.get(order_number, []).append(venta["id"])
    
    duplicates = 0
    orders = 0
    for boleta in vouchers:
      if len(vouchers[boleta]) > 1:
        duplicates += len(vouchers[boleta])
        orders += 1
    if duplicates > 0:
      logger.error("There are {} duplicate boletas for {} ...".format(duplicates, orders))
      with open("duplicate_boletas.csv", "w") as f:
        if options["save"]:
          f.write("order_number,boleta_id\n")
        for order_number in vouchers:
          logger.info("order {}, duplicates {}".format(order_number, len(vouchers[order_number])))
          if options["save"]:
            boletas = vouchers[boleta]
            for boleta_id in boletas:
              f.write("{},{}\n".format(order_number,boleta_id))
      raise CommandError("Inconsistency detected")

    # No duplicates so far
    # CHECK TWO:
    # Verify that we have these boletas recorded at ecommerce
    voucher_ids = [vouchers[b][0] for b in vouchers]
    not_recorded = []
    for boleta_id in voucher_ids:
      try:
        b = BoletaElectronica.objects.get(voucher_id=boleta_id)
      except BoletaElectronica.DoesNotExist:
        not_recorded.append(boleta_id)
    if len(not_recorded) == 0:
      logger.error("Some boletas are not registered on ecommerce but created at ventas API. Total {}".format(len(not_recorded)))
      logger.info(not_recorded)
      if options["save"]:
        with open("missing_boletas.csv", "w") as f:
          f.write("boleta\n{}".format("\n".join(not_recorded)))
      raise CommandError("Inconsistency detected")


    # CHECK THREE
    # Make sure the counts are correct
    local_count = BoletaElectronica.objects.filter(emission_date__gte=since).count()
    if voucher_ids != local_count:
        logger.error("Boleta count is inconsistent. Local {} - Remote {}".format(local_count, voucher_ids))
        raise CommandError("Inconsistency detected")

    # They exists
    # All OK
    logger.info("All OK from here :)")