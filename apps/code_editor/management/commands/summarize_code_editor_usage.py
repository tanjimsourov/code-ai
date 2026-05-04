from django.core.management.base import BaseCommand, CommandError

from ...services.usage_service import UsageService


class Command(BaseCommand):
    help = 'Summarize code editor usage from request logs'

    def add_arguments(self, parser) -> None:
        parser.add_argument('--days', type=int, default=30)

    def handle(self, *args, **options) -> None:
        days = int(options['days'])
        try:
            stats = UsageService.get_usage_stats(days=days)
        except Exception as exc:
            raise CommandError(f'Failed to summarize usage: {exc}') from exc

        summary = stats.get('summary', {})
        self.stdout.write(f"Period days: {days}")
        self.stdout.write(f"Total requests: {summary.get('total_requests', 0)}")
        self.stdout.write(f"Successful requests: {summary.get('successful_requests', 0)}")
        self.stdout.write(f"Error requests: {summary.get('error_requests', 0)}")
        self.stdout.write(f"Success rate: {summary.get('success_rate', 0)}%")
