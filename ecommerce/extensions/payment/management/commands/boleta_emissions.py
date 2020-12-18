import logging
import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ecommerce.extensions.payment.models import UserBillingInfo
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, make_boleta_electronica

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = """Create boletas from unused user billing info."""
    requires_migrations_checks = True

    def handle(self, *args, **options):

        completed = 0
        failed = 0

        # Get not used billing info
        billing_info = UserBillingInfo.objects.filter(boleta=None)
        for info in billing_info:
            try:
                basket = info.basket
                auth = authenticate_boleta_electronica()
                boleta_id = make_boleta_electronica(basket, basket.total_incl_tax, auth)
                completed = completed + 1
            except requests.exceptions.ConnectionError:
                failed = failed + 1
                logger.warning("Coudn't connect to boleta API for{}".format(info), exc_info=True)
            except Exception:
                failed = failed + 1
                logger.warning("Error while processing boleta for  {}".format(info), exc_info=True)

        logger.info("Completed {}, Failed {}, Total {}".format(completed,failed,len(billing_info)))
        
