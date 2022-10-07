import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import EmailMessage

from ecommerce.extensions.payment.models import BoletaElectronica
from ecommerce.extensions.payment.boleta import authenticate_boleta_electronica, get_boletas


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = """Recover boleta's info, counts and verifies that there are no duplicates or inconsistencies"""
    requires_migrations_checks = True

    def send_email_with_attachment(self, subject, message, file_path):
        mail = EmailMessage(
            subject, message,
            settings.BOLETA_CONFIG.get("from_email",None),
            [settings.BOLETA_CONFIG.get("team_email","")])
        if file_path is not None:
            mail.attach_file(file_path)
        mail.send(fail_silently=False)

    def write_local_boletas(self, boleta_objects, filename):
        with open(filename,"w") as f:
            f.write("order_number,total,date_placed,boleta_id\n")
            for local_boleta in boleta_objects:
                f.write("{},{},{},{}\n".format(
                    local_boleta["basket__order__number"],
                    local_boleta["basket__order__total_incl_tax"],
                    local_boleta["basket__order__date_placed"],
                    local_boleta["voucher_id"]))

    def write_remote_boletas(self, boletas, exists, data, filename):
        with open(filename, "w") as f:
            f.write("order_number,boleta_id,folio,fecha,monto,on_DB\n")
            c = 0
            for boleta_id in boletas:
                f.write("{},{},{},{},{},{}\n".format(
                    data[boleta_id]["puntoVenta"]["rutCajero"],
                    boleta_id,
                    data[boleta_id]["boleta"]["folio"],
                    data[boleta_id]["boleta"]["fechaEmision"],
                    data[boleta_id]["recaudaciones"][0]["monto"],
                    exists[c]))
                c += 1

    def register_duplicates(self, order_numbers, data):
        """
        Arguments
            order_numbers dictionary with order_number as key
                and a list of boleta_id hashes
            data dictionary with raw data for each
                boleta by id
        """
        duplicates_boleta_ids = []
        for order_number in order_numbers:
            count = len(order_numbers[order_number])
            if count > 1:
                logger.info("order {}, duplicates_boleta_ids {}".format(
                    order_number, count))
                duplicates_boleta_ids.extend(order_numbers[order_number])
        if len(duplicates_boleta_ids) > 0 and self.save:
            exists = []
            # Check if the order is locally saved
            for boleta_id in duplicates_boleta_ids:
                try:
                    BoletaElectronica.objects.get(voucher_id=boleta_id)
                    exists.append(True)
                except BoletaElectronica.DoesNotExist:
                    exists.append(False)
            self.write_remote_boletas(duplicates_boleta_ids, exists, data, "duplicate_boletas.csv")
            if self.email:
                self.send_email_with_attachment(
                    "[Ecommerce] Existen boletas duplicadas",
                    "El comando get_boleta_emissions reportó boletas duplicadas en la API de Ventas UChile. Se adjuntan detalles.",
                    "/openedx/ecommerce/duplicate_boletas.csv"
                )

    def verify_local_count_is_zero(self, since):
        """
        If local count is zero return.
        Raise CommandError otherwise

        Send email with local boletas details if enabled
        """
        local_count = BoletaElectronica.objects.filter(
            emission_date__gte=since).count()
        if local_count == 0:
            logger.info("No Local Boletas. Exiting")
            return
        else:
            logger.error(
                "Inconsistency detected: Local count exists but it has been remotely removed by Ventas API")
            # Email and report logic
            if self.save:
                local = BoletaElectronica.objects \
                    .filter(emission_date__gte=since) \
                    .values(
                        "basket__order__number",
                        "basket__order__total_incl_tax",
                        "basket__order__date__placed",
                        "voucher_id")
                self.write_local_boletas(local, "local_boletas.csv")
                if self.email:
                    self.send_email_with_attachment(
                        "[Ecommerce] Inconsistencia con API",
                        "Existen boletas locales pero ninguna boleta en la API. Puede que hayan sido borradas.",
                        "/openedx/ecommerce/local_boletas.csv")
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
            if venta["puntoVenta"]["rutCajero"] is None:
                logger.info("Boleta_id {}, viene con un order_number None".format(venta['id']))
                continue
            order_number = venta["puntoVenta"]["rutCajero"]
            try:
                aux = order_number.split('UA')
                order_number = "UA-{}".format(aux[1])
            except Exception as e:
                logger.error("Error get_boleta_emissions in order_number from rutCajero, error: {}".format(str(e)))
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
            logger.error("There are {} duplicate boletas for {} orders. boletas: {}".format(
                duplicates, orders, raw_data))
            # map ids to a dict
            boletas_data = {}
            for item in raw_data:
                boletas_data[item["id"]] = item
            self.register_duplicates(remote_boleta_orders, boletas_data)
            raise CommandError("Inconsistency detected")
        return remote_boleta_orders

    def find_on_local_db(self, order_boleta_pairs, raw_data):
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
            logger.error("Some boletas are not registered on ecommerce but created at ventas API. Total {}".format(len(not_recorded)))
            logger.info(not_recorded)
            # Reporting and email logic
            if self.save:
                # map ids to a dict
                boletas_data = {}
                for item in raw_data:
                    boletas_data[item["id"]] = item
                self.write_remote_boletas(not_recorded,
                    [False for b in not_recorded],
                    boletas_data, "missing_boletas.csv")
                if self.email:
                    self.send_email_with_attachment(
                        "[Ecommerce] Inconsistencia de boletas",
                        "El comando get_boleta_emissions reportó boletas que existen en la API de Ventas UChile y no localmente. Se adjuntan detalles.",
                        "/openedx/ecommerce/missing_boletas.csv"
                    )

            raise CommandError("Inconsistency detected")

    def find_missing_locals(self, order_boleta_pairs, since):
        """
        By this point the only option is that we have more
        boletas locally (because of the previous checks)

        Compare if remote and local counts match.
        Otherwise register errors and missing elements.

        NOTE: some errors have arisen from timezone mistakes
        """
        def list_diff(l1,l2):
            second = set(l2)
            return [item for item in l1 if item not in second]

        local = BoletaElectronica.objects.filter(
            emission_date__gte=since)
        local_count = local.count()
        if len(order_boleta_pairs) < local_count:
            logger.error(
                "Boleta count is inconsistent. Local {} - Remote {}".format(local_count, len(order_boleta_pairs)))
            remote_boleta_ids = [b[1] for b in order_boleta_pairs] # Tuples
            local_boletas = [b.voucher_id for b in local]
            local_diff = list_diff(local_boletas, remote_boleta_ids)
            logger.info("These boletas are only locally available {}".format(local_diff))
            # Reporting and email logic
            if self.save:
                local_boletas = BoletaElectronica.objects \
                        .filter(voucher_id__in=local_diff) \
                        .values(
                            "basket__order__number",
                            "basket__order__total_incl_tax",
                            "basket__order__date_placed",
                            "voucher_id")
                self.write_local_boletas(local_boletas, "only_local_boletas.csv")
                if self.email:
                    self.send_email_with_attachment(
                        "[Ecommerce] Inconsistencia de boletas",
                        "Existe una diferencia al contar boletas remotas y locales. En particular las boletas {} existen solo localmente. Detalle adjunto.".format(local_diff),
                        "/openedx/ecommerce/only_local_boletas.csv")
            raise CommandError("Inconsistency detected")

    def add_arguments(self, parser):
        # Optional argument
        parser.add_argument("since", action='store',
                            help="Starting ISO date without TZ")
        parser.add_argument(
            "-s", "--save", action='store_true', help="Save to file")
        parser.add_argument(
            "-e", "--email", action='store_true', help="Send to support email")

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
        self.email = options["email"]
        self.save = options["save"]
        # Emails require a saved file
        if self.email:
            self.save = True

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
        self.find_on_local_db(order_boleta_pairs, raw_boletas)

        # CHECK THREE (maybe redundant)
        # Make sure the counts are correct
        self.find_missing_locals(order_boleta_pairs, options["since"])

        # They exists
        # All OK
        logger.info("All OK from here :)")
