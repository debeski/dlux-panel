from django.core.management.base import BaseCommand

from fleet.retention import prune_operation_logs


class Command(BaseCommand):
    help = "Clear sanitized fleet operation log bodies older than the retention window"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None)

    def handle(self, *args, **options):
        count = prune_operation_logs(options["days"])
        self.stdout.write(self.style.SUCCESS(f"Cleared {count} expired operation log bodies."))
