import logging
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from oscar.core.loading import get_model, get_class
from oscar.apps.partner import strategy

from ecommerce.extensions.payment.models import BoletaElectronica
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, get_boleta_details

Order = get_model('order','Order')
Basket = get_model('basket','Basket')

logger = logging.getLogger(__name__)

class Command(BaseCommand):
  help = """Recover boleta's info and put it into a csv file"""
  requires_migrations_checks = True

  def add_arguments(self, parser):
    # Optional argument
    parser.add_argument("-l", "--list", nargs='+', help="List of boleta ids to complete")

  def handle(self, *args, **options):

    boleta_active = hasattr(settings, 'BOLETA_CONFIG') and settings.BOLETA_CONFIG.get("enabled",False)
    if not boleta_active:
      logger.error("BOLETA_CONFIG is not set or enabled, enable it on your settings to run this commmand")
      return
    
    if options["list"] is not None and len(options["list"]) > 0:
      boletas = []
      for b_id in options["list"]:
        try:
          boleta.append( BoletaElectronica.objects.get(voucher_id=b_id))
        except Exception:
          logger.exception("Error getting boleta electronica {}. Skipping ...".format(b_id))
    else:
      boletas = BoletaElectronica.objects.all()
    if boletas.count() == 0:
      logger.info("No Boletas yet :)")
      return
    
    with open("boletas.csv", "w") as file:
      # Write header
      file.write("basket_id,basket_user,basket_amount,order_amount,order_placed,order_number,boleta_amount,boleta_id,boleta_folio,boleta_emission_date\n")

      for boleta in boletas:
        try:
          # Get Basket
          basket = Basket.objects.get(pk=boleta.basket.pk)
          basket.strategy = strategy.Default()

          # Get Order
          order_number = basket.order_number
          order = Order.objects.get(number=order_number)
          
          # Write data
          file.write("{},{},{},{},{},{},{},{},{}\n".format(basket.id,basket.owner,basket.total_incl_tax,order.total_incl_tax,order.date_placed,order_number,boleta.amount, boleta.voucher_id, boleta.folio, boleta.emission_date))
        except Exception as e:
          logger.error(str(e), exc_info=True)
      
      logger.info("Wrote to file boletas.csv {}".format(boleta.voucher_id))
    