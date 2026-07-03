# Testing dan Benchmark Guide

## Seed Data Besar

```bash
python manage.py seed_data
```

Default command akan membuat minimal:

- 20 instructor
- 200 student
- 100 course
- 500 enrollment
- 1000 komentar

Nilai dapat diubah:

```bash
python manage.py seed_data --teachers 20 --students 200 --courses 100 --members 500 --comments 1000
```

## Coverage Minimal 80%

```bash
coverage run manage.py test
coverage report
coverage html
```

File `.coveragerc` sudah disiapkan dengan `fail_under = 80`.

## Locust Load Test

```bash
locust -f locustfile.py --host=http://localhost:8000
```

Buka UI Locust lalu jalankan simulasi user untuk endpoint course list, search/sort/pagination, analytics popular courses, dan Swagger docs.

## Benchmark Database + Redis Cache

```bash
python manage.py benchmark_lms --iterations 5
```

Hasil default akan dibuat di:

```text
docs/BENCHMARK_RESULTS.md
```

## Redis Cache Metrics

Endpoint admin:

```text
GET  /api/v1/cache/metrics
POST /api/v1/cache/metrics/reset
```

## MongoDB Raw Logs

Endpoint admin:

```text
GET    /api/v1/analytics/activity-logs/
PATCH  /api/v1/analytics/activity-logs/{log_id}/
DELETE /api/v1/analytics/activity-logs/{log_id}/
GET    /api/v1/analytics/request-logs/
```

## RabbitMQ dan Flower

RabbitMQ Management UI:

```text
http://localhost:15672
```

Flower:

```text
http://localhost:5555
```

Pastikan `.env` sudah memiliki credential RabbitMQ yang sama dengan `CELERY_BROKER_URL`.
