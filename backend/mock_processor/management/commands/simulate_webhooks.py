from django.core.management.base import BaseCommand, CommandError

from mock_processor.webhooks import MODES, UnknownCharge, deliver_with_mode


class Command(BaseCommand):
    help = "Deliver a charge's webhook events in a messy way: normal, duplicate, reverse or concurrent."

    def add_arguments(self, parser):
        parser.add_argument("--reference", required=True, help="processor_reference, e.g. pr_91c2...")
        parser.add_argument("--mode", required=True, choices=MODES)

    def handle(self, *args, **options):
        try:
            results = deliver_with_mode(options["reference"], options["mode"])
        except UnknownCharge:
            raise CommandError(f"No charge with reference {options['reference']}")

        for event_id, status, http_status in results:
            self.stdout.write(f"{event_id}  {status:<9}  -> HTTP {http_status}")
