# Benchmark Results — Simple LMS

Benchmark ini dibuat dengan `python manage.py benchmark_lms` untuk membuktikan optimasi database dan Redis cache.

| Endpoint | Status | First ms | First queries | Warm avg ms | Warm avg queries | Path |
|---|---:|---:|---:|---:|---:|---|
| Course list | 200 | 113.08 | 2 | 17.6 | 0 | `/api/v1/courses?page=1&page_size=10` |
| Course search+sort | 200 | 43.13 | 2 | 13.95 | 0 | `/api/v1/courses?search=python&ordering=-created_at&page=1&page_size=10` |
| Course detail | 200 | 118.05 | 1 | 8.37 | 0 | `/api/v1/courses/1` |

## Redis Cache Metrics

```json
{
  "hits": 15,
  "misses": 3,
  "total": 18,
  "hit_rate_percent": 83.33
}
```

Catatan: angka bergantung pada kondisi mesin, jumlah data seed, dan apakah Redis/PostgreSQL sudah warm.