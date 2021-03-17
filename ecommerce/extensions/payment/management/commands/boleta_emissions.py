import logging
import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import send_mail
from oscar.core.loading import get_model
from oscar.apps.partner import strategy

from ecommerce.extensions.payment.models import UserBillingInfo, BoletaErrorMessage
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, make_boleta_electronica

Order = get_model('order','Order')
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = """Create boletas from unused user billing info."""
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", help="Run without applying changes", action='store_true')

    def handle(self, *args, **options):

        boleta_active = hasattr(settings, 'BOLETA_CONFIG') and settings.BOLETA_CONFIG.get("enabled",False)
        if not boleta_active:
            logger.error("BOLETA_CONFIG is not set or enabled, enable it on your settings to run this commmand")
            return

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
                basket.strategy = strategy.Default()

                if not dry_run:
                    auth = authenticate_boleta_electronica(basket=basket)
                    boleta_id = make_boleta_electronica(basket, order, auth)
                    
                completed = completed + 1
                logger.info("Completed Boleta for order {}, user {}, amount CLP {}".format(order.number,basket.owner.username, order.total_incl_tax))
            except requests.exceptions.ConnectionError:
                failed = failed + 1
                logger.warning("Coudn't connect to boleta API for: {}".format(info), exc_info=True)
            except Exception:
                failed = failed + 1
                logger.warning("Error while processing boleta for: {}".format(info), exc_info=True)
        if not dry_run:
            # Check for errors and recover messages
            error_messages = BoletaErrorMessage.objects.all()
            # No orders, no errors
            if error_messages.count() > 0:

                # TODO: Support multisite configuration for each error
                site = orders[0].site

                message = "Lugar: comando boleta_emissions\nDescripción: Hubieron errores al generar las boletas con el comando boleta_emissions\n\nEn total {} error(es)\n".format(error_messages.count())
                for m in error_messages:
                    message = message+"Codigo {}, mensaje\n{}\n".format(m.code, m.content)
                # Append site footer
                message = message+"Originado en {} con partner {}".format(site.domain,site.siteconfiguration.lms_url_root)

                send_mail(
                    'Boleta Electronica API Error(s)',
                    message,
                    settings.BOLETA_CONFIG.get("from_email",None),
                    [settings.BOLETA_CONFIG.get("team_email","")],
                    fail_silently=False
                )

                # All ok, flush messages
                error_messages.delete()

        logger.info("Completed {}, Failed {}, Total {}".format(completed,failed,completed+failed))
        