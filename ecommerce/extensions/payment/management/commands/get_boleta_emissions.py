import logging
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from oscar.core.loading import get_model, get_class
from oscar.apps.partner import strategy

from ecommerce.extensions.payment.models import BoletaElectronica
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, get_boletas

Order = get_model('order', 'Order')
Basket = get_model('basket', 'Basket')

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = """Recover boleta's info, counts and verifies that there are no duplicates or inconsistencies"""
    requires_migrations_checks = True

    def register_duplicates(self, order_numbers):
        with open("duplicate_boletas.csv", "w") as f:
            if self.save:
                f.write("order_number,boleta_id\n")
            for order_number in order_numbers:
                logger.info("order {}, duplicates {}".format(
                    order_number, len(order_numbers[order_number])))
                if self.save:
                    boletas = order_numbers[boleta]
                    for boleta_id in boletas:
                        f.write("{},{}\n".format(order_number, boleta_id))

    def verify_local_count_is_zero(self, since):
        """
        If local count is zero return. Raise CommandError otherwise
        """
        local_count = BoletaElectronica.objects.filter(
            emission_date__gte=since).count()
        if local_count == 0:
            logger.info("No Local Boletas. Exiting")
            return
        else:
            logger.error(
                "Inconsistency detected: Local count exists but it has been remotely removed by Ventas API")
            raise CommandError("Inconsistency detected")

    def look_for_duplicates(self, raw_data):
        """
        Group boletas by order_number and check
        if we have 1 order_number to 1 boleta_id
        """
        duplicates = 0
        orders = 0
        remote_boleta_orders = {}

        # Pair order to (hopefully just one) hash boleta_ids
        for venta in raw_data:
            order_number = venta["recaudaciones"][0]["voucher"]
            prev = remote_boleta_orders.get(
                order_number, [])
            prev.append(venta["id"])
            remote_boleta_orders[order_number] = prev
        # Count
        for boleta in remote_boleta_orders:
            if len(remote_boleta_orders[boleta]) > 1:
                duplicates += len(remote_boleta_orders[boleta])
                orders += 1
        if duplicates > 0:
            logger.error("There are {} duplicate boletas for {} ...".format(
                duplicates, orders))
            self.register_duplicates(remote_boleta_orders)
            raise CommandError("Inconsistency detected")
        return remote_boleta_orders

    def compare_to_locals(self, order_boleta_pairs):
        """
        Make a list of boleta_ids and try to find it
        locally on the DB.
        """
        boleta_ids = [b[1] for b in order_boleta_pairs]
        not_recorded = []
        for boleta_id in boleta_ids:
            try:
                b = BoletaElectronica.objects.get(voucher_id=boleta_id)
            except BoletaElectronica.DoesNotExist:
                not_recorded.append(boleta_id)
        if len(not_recorded) != 0:
            logger.error("Some boletas are not registered on ecommerce but created at ventas API. Total {}".format(
                len(not_recorded)))
            logger.info(not_recorded)
            if self.save:
                with open("missing_boletas.csv", "w") as f:
                    f.write("boleta\n{}".format("\n".join(not_recorded)))
            raise CommandError("Inconsistency detected")

    def compare_remote_and_local_counts(self, order_boleta_pairs, since):
        """
        Compare if remote and local counts match.
        Otherwise register errors and missing elements.
        """
        local = BoletaElectronica.objects.filter(
            emission_date__gte=since)
        local_count = local.count()
        if len(order_boleta_pairs) != local_count:
            logger.error(
                "Boleta count is inconsistent. Local {} - Remote {}".format(local_count, len(order_boleta_pairs)))
            remote_boleta_ids = [b[1] for b in order_boleta_pairs]
            local_boletas = [b.voucher_id for b in local]
            remote_boleta_ids.sort()
            local_boletas.sort()
            logger.info("Local {}".format(local_boletas))
            logger.info("Remote {}".format(remote_boleta_ids))
            raise CommandError("Inconsistency detected")

    def add_arguments(self, parser):
        # Optional argument
        parser.add_argument("since", action='store',
                            help="Starting ISO date without TZ")
        parser.add_argument(
            "-s", "--save", action='store_true', help="Save to file")

    def handle(self, *args, **options):
        """
        Verify consistency in the following steps
        - Recover boletas from API with state INGRESADA and CONTABILIZADA
        - Group boleta_ids by order_number and verify that we have no duplicates
        - See if the boletas recorded remotely are locally available
        - Compare local to remote counts
        """

        boleta_active = hasattr(
            settings, 'BOLETA_CONFIG') and settings.BOLETA_CONFIG.get("enabled", False)
        if not boleta_active:
            logger.error(
                "BOLETA_CONFIG is not set or enabled, enable it on your settings to run this commmand")
            return
        self.save = options["save"]

        # Get boletas registry from API
        auth = authenticate_boleta_electronica()
        headers = {
            "Authorization": "Bearer " + auth["access_token"]
        }
        raw_boletas = get_boletas(headers, options["since"])
        raw_boletas.extend(get_boletas(headers, options["since"], state="INGRESADA"))

        # CHECK ZERO
        # Verify that counts are consistent
        if len(raw_boletas) == 0:
            logger.info(
                "No boletas INGRESADAs recovered from Ventas API. Checking local count ...")
            self.verify_local_count_is_zero(options["since"])

        # CHECK ONE:
        # Process boletas and review duplicates
        grouped_boleta = self.look_for_duplicates(raw_boletas)

        order_boleta_pairs = [(b, grouped_boleta[b][0]) for b in grouped_boleta]

        # No duplicates so far
        # CHECK TWO:
        # Verify that we have these boletas recorded at ecommerce
        self.compare_to_locals(order_boleta_pairs)

        # CHECK THREE
        # Make sure the counts are correct
        self.compare_remote_and_local_counts(order_boleta_pairs, options["since"])

        # They exists
        # All OK
        logger.info("All OK from here :)")
