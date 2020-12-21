import logging
import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from oscar.core.loading import get_model

from ecommerce.extensions.payment.models import UserBillingInfo
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, make_boleta_electronica

Order = get_model('order','Order')
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = """Create boletas from unused user billing info."""
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", help="Run without applying changes", action='store_true')

    def handle(self, *args, **options):

        dry_run = False
        if options["dry_run"]:
            dry_run = True

        completed = 0
        failed = 0

        # Get payed orders
        orders = Order.objects.filter(status="Complete")

        for order in orders:
            try:
                # Get not used billing info 
                # Each basket is unique and should only have 
                # one user billing info object. 
                # (avoid DoesNotExist Exception)
                info = UserBillingInfo.objects.filter(basket=order.basket, boleta=None)
                if len(info) != 1:
                    continue
                info = info[0]
                basket = info.basket

                if not dry_run:
                    auth = authenticate_boleta_electronica()
                    boleta_id = make_boleta_electronica(basket, basket.total_incl_tax, auth)
                    
                completed = completed + 1
                logger.info("Completed Boleta for order {}, user {}, amount CLP {}".format(order.number,basket.owner.username, order.total_incl_tax))
            except requests.exceptions.ConnectionError:
                failed = failed + 1
                logger.warning("Coudn't connect to boleta API for{}".format(info), exc_info=True)
            except Exception:
                failed = failed + 1
                logger.warning("Error while processing boleta for {}".format(info), exc_info=True)

        logger.info("Completed {}, Failed {}, Total {}".format(completed,failed,completed+failed))
        
