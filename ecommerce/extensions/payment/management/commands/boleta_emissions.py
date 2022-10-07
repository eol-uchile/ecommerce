import logging
import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.core.cache import cache
from oscar.core.loading import get_model
from oscar.apps.partner import strategy

from ecommerce.extensions.payment.models import UserBillingInfo, BoletaErrorMessage
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, make_boleta_electronica

Order = get_model('order','Order')
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = """Create boletas from unused user billing info."""
    requires_migrations_checks = True

    def get_auth_from_cache(self, basket):
        """
        Save authentication credentials on cache for half it's lifetime
        """
        auth = cache.get("boleta_emissions_auth_cache", None)
        if auth == None or auth["expires_in"] < 20:
            auth = authenticate_boleta_electronica(basket=basket)
            cache.set("boleta_emissions_auth_cache", auth, auth["expires_in"]//2)
        return auth

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", help="Run without applying changes", action='store_true', default=False)
        parser.add_argument("--processor", help="Payment processor name used (webpay or paypal)", default="webpay")
        parser.add_argument("--order-number", nargs="+", help="Subset of orders to process like EOL-10001", required=False)

    def handle(self, *args, **options):

        boleta_active = hasattr(settings, 'BOLETA_CONFIG') and settings.BOLETA_CONFIG.get("enabled",False)
        if not boleta_active:
            logger.error("BOLETA_CONFIG is not set or enabled, enable it on your settings to run this commmand")
            return

        dry_run = options["dry_run"]
        payment_processor = options["processor"]

        completed = 0
        failed = 0

        # Get payed orders
        orders = Order.objects.filter(status="Complete", basket__boletaelectronica=None, total_incl_tax__gt=0, basket__userbillinginfo__payment_processor=payment_processor)

        if options["order_number"] is not None and len(options["order_number"]) > 0:
            orders = orders.filter(number__in=options["order_number"])

        for order in orders:
            try:
                # We re-check if there is a boleta associated to the basket via the userbillinginfo
                used_info = UserBillingInfo.objects.filter(basket=order.basket).exclude(boleta=None)
                if used_info.count() > 0:
                    logger.warning("Order {} is complete, but without the proper association with it's boleta {}".format(order.number, used_info.first().boleta))
                    continue

                info = UserBillingInfo.objects.get(basket=order.basket, boleta=None, payment_processor=payment_processor)

                basket = info.basket
                basket.strategy = strategy.Default()

                if not dry_run:
                    auth = self.get_auth_from_cache(basket)
                    boleta_id = make_boleta_electronica(basket, order, auth, payment_processor=payment_processor)

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

