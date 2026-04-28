from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "No-op helper. Retry checks are scheduled per payout at runtime."

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("No bootstrap needed. Retry checks are scheduled automatically per payout.")
        )
