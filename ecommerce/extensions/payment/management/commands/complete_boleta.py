import logging
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from ecommerce.extensions.payment.models import BoletaElectronica
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, get_boleta_details

logger = logging.getLogger(__name__)

class Command(BaseCommand):
  help = """Complete boleta details recovering missing info from API"""
  requires_migrations_checks = True

  def add_arguments(self, parser):
    # Optional argument
    parser.add_argument("-l", "--list", nargs='+', help="List of boleta ids to complete")
    parser.add_argument("--dry-run", help="Run without applying changes", action='store_true', default=False)

  def handle(self, *args, **options):

    boleta_active = hasattr(settings, 'BOLETA_CONFIG') and settings.BOLETA_CONFIG.get("enabled",False)
    if not boleta_active:
      logger.error("BOLETA_CONFIG is not set or enabled, enable it on your settings to run this commmand")
      return
    
    if options["list"] is not None and len(options["list"]) > 0:
      boletas = []
      for b_id in options["list"]:
        try:
          boletas.append( BoletaElectronica.objects.get(voucher_id=b_id))
        except Exception:
          logger.exception("Error getting boleta electronica {}. Skipping ...".format(b_id))
      if len(boletas) == 0:
        logger.info("No Boletas to complete")
        return
    else:
      boletas = BoletaElectronica.objects.filter(emission_date=None, folio="")
      if boletas.count() == 0:
        logger.info("No Boletas to complete")
        return
    
    # Complete each boleta's info
    for boleta in boletas:
      try:
        auth = authenticate_boleta_electronica()
        headers = {"Authorization": "Bearer " + auth["access_token"]}
        details = get_boleta_details(boleta.voucher_id, headers)
        if not options["dry_run"]:
          # Update
          boleta.folio = details["boleta"]["folio"]
          boleta.emission_date = datetime.fromisoformat(details["boleta"]["fechaEmision"])
          boleta.amount = int(details["recaudaciones"][0]["monto"])
          boleta.save()
        
        logger.info("Recovered data for boleta {}".format(boleta.voucher_id))
      except Exception as e:
        logger.error("Something went wrong updating boleta {}".format(boleta.voucher_id), exc_info=True)
    