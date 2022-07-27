import logging
import requests

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from oscar.core.loading import get_model

from ecommerce.extensions.payment.processors.webpay import Webpay

Basket = get_model('basket','Basket')
PaymentProcessorResponse = get_model('payment', 'PaymentProcessorResponse')
Site = get_model('sites','Site')
User = get_user_model()
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = """Looks up the status of a transaction given a token, student or basket.

    It allows to lookup transaction using either:
    - a list of tokens
    - a user email to fetch all token transactions for frozen baskets
    - a list of order numbers like EOL-201001 EOL-201002
    Each search is done independently

    Example:
        python manage.py inspect_webpay EOL -t as8da862da7sd98as8d87 fdddsa862da7sd91231245 -o EOL-201001 EOL-201002"""
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument("partner_short_code", help="Partner short code like EOL or EDX")
        parser.add_argument("-t", "--token", nargs='+', help="List of tokens separated by space", required=False, default=[])
        parser.add_argument("-o", "--order-id", nargs='+', help="List of order-ids to recover the transaction state", required=False, default="")
        parser.add_argument("-u", "--user", help="User email to recover his frozen transactions", required=False, default=[])
    
    def get_response(self,token):
        result = requests.post(self.processor.configuration["api_url"]+"/transaction-status", json={
            "api_secret": self.processor.configuration["api_secret"],
            "token": token
        })
        return result

    def find_processor_response(self,transaction_id):
        responses = PaymentProcessorResponse.objects.filter(
                processor_name=self.processor.NAME,
                transaction_id=transaction_id
            ).exclude(basket=None)
        responses_count = responses.count()
        if responses_count > 1:
            logger.warning("Got {} processor responses, using first to recover basket".format(responses_count))
        elif responses_count == 0:
            logger.error("No responses found for order number {}".format(transaction_id))
            return []

        return responses
    
    def find_processor_response_by_basket(self,basket_id):
        responses = PaymentProcessorResponse.objects.filter(
                processor_name=self.processor.NAME,
                basket=basket_id
            ).exclude(transaction_id=None)
        responses_count = responses.count()
        if responses_count > 1:
            logger.warning("Got {} processor responses, using first to recover basket".format(responses_count))
        elif responses_count == 0:
            logger.error("No responses found for basket {}".format(basket_id))
            return []

        return responses

    def log_tokens(self, tokens):
        for token in tokens:
            result = self.get_response(token)
            if result.status_code == 403 or result.status_code == 500:
                logger.error("Service didn't respond to token {}".format(token))
            else:
                logger.info("Recovered status {}".format(result.json()))

    def handle(self, *args, **options):
        site = Site.objects.get(partner__short_code=options["partner_short_code"])
        self.processor = Webpay(site)

        # Do tokens
        self.log_tokens(options["token"])
    
        # Do order numbers
        for order in options["order_id"]:
            logger.info("Doing order: {}".format(order))
            responses = self.find_processor_response(order)
            tokens = [resp.response["token"] for resp in responses]
            self.log_tokens(tokens)

        # Do user transactions
        if options["user"] is not None:
            user = options["user"]
            logger.info("Finding transactions for user {}".format(user))
            try:
                user = User.objects.get(email=user)
                baskets = Basket.objects.filter(owner=user, status="Frozen")
                logger.info("Found {} baskets associated to user {}".format(baskets.count(), user))
                for b in baskets:
                    responses = self.find_processor_response_by_basket(b)
                    tokens = [resp.response["token"] for resp in responses]
                    self.log_tokens(tokens)
            except User.DoesNotExist:
                logger.exception("User doesn't exist!")
