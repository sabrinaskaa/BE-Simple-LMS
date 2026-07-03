import time
from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand

from analytics import mongo_service


class Command(BaseCommand):
    help = "Benchmark sederhana MongoDB aggregation untuk activity_logs."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--limit", type=int, default=10)

    def handle(self, *args, **options):
        days = max(options["days"], 1)
        limit = max(options["limit"], 1)
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        self.stdout.write("Menjalankan benchmark MongoDB aggregation...")
        started = time.perf_counter()
        popular = mongo_service.get_popular_courses(limit=limit)
        popular_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        daily = mongo_service.get_daily_activity_summary(start_date=start_date, end_date=end_date)
        daily_ms = (time.perf_counter() - started) * 1000

        self.stdout.write(self.style.SUCCESS("Benchmark selesai"))
        self.stdout.write(f"popular_courses_ms={popular_ms:.2f}, rows={len(popular)}")
        self.stdout.write(f"daily_summary_ms={daily_ms:.2f}, rows={len(daily)}")
