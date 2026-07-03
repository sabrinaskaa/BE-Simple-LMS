import json
import statistics
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection, reset_queries
from django.test import Client, override_settings

from courses.cache import get_cache_metrics, reset_cache_metrics
from courses.models import Course


class Command(BaseCommand):
    help = "Benchmark sederhana untuk pembuktian optimasi database dan Redis cache Simple LMS."

    def add_arguments(self, parser):
        parser.add_argument("--iterations", type=int, default=5, help="Jumlah request per endpoint")
        parser.add_argument("--output", default="docs/BENCHMARK_RESULTS.md", help="Path output markdown")

    @override_settings(DEBUG=True)
    def handle(self, *args, **options):
        iterations = max(1, options["iterations"])
        output = Path(options["output"])
        output.parent.mkdir(parents=True, exist_ok=True)

        client = Client()
        endpoints = [
            ("Course list", "/api/v1/courses?page=1&page_size=10"),
            ("Course search+sort", "/api/v1/courses?search=python&ordering=-created_at&page=1&page_size=10"),
        ]
        first_course = Course.objects.order_by("id").first()
        if first_course:
            endpoints.append(("Course detail", f"/api/v1/courses/{first_course.id}"))

        reset_cache_metrics()
        rows = []
        for label, path in endpoints:
            # Cold-ish request pertama untuk mengisi cache.
            reset_queries()
            t0 = time.perf_counter()
            response = client.get(path)
            first_ms = (time.perf_counter() - t0) * 1000
            first_queries = len(connection.queries)

            warm_times = []
            warm_queries = []
            for _ in range(iterations):
                reset_queries()
                t0 = time.perf_counter()
                response = client.get(path)
                elapsed = (time.perf_counter() - t0) * 1000
                warm_times.append(elapsed)
                warm_queries.append(len(connection.queries))

            rows.append({
                "endpoint": label,
                "path": path,
                "status_code": response.status_code,
                "first_request_ms": round(first_ms, 2),
                "first_request_queries": first_queries,
                "warm_avg_ms": round(statistics.mean(warm_times), 2),
                "warm_avg_queries": round(statistics.mean(warm_queries), 2),
            })

        cache_metrics = get_cache_metrics()
        lines = [
            "# Benchmark Results — Simple LMS",
            "",
            "Benchmark ini dibuat dengan `python manage.py benchmark_lms` untuk membuktikan optimasi database dan Redis cache.",
            "",
            "| Endpoint | Status | First ms | First queries | Warm avg ms | Warm avg queries | Path |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
        for row in rows:
            lines.append(
                f"| {row['endpoint']} | {row['status_code']} | {row['first_request_ms']} | "
                f"{row['first_request_queries']} | {row['warm_avg_ms']} | {row['warm_avg_queries']} | `{row['path']}` |"
            )
        lines.extend([
            "",
            "## Redis Cache Metrics",
            "",
            "```json",
            json.dumps(cache_metrics, indent=2),
            "```",
            "",
            "Catatan: angka bergantung pada kondisi mesin, jumlah data seed, dan apakah Redis/PostgreSQL sudah warm.",
        ])
        output.write_text("\n".join(lines), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Benchmark selesai. Hasil: {output}"))
