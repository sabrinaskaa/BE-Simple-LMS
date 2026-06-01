# Task Flow Documentation

## BE Simple LMS - Redis, MongoDB, RabbitMQ, Celery

## 1. Ringkasan Arsitektur

Proyek BE Simple LMS menggunakan Django Ninja sebagai backend API utama. Client seperti Swagger UI atau Postman mengirim request HTTP ke Django Ninja API.

Django Ninja API terhubung dengan beberapa service pendukung:

- PostgreSQL digunakan sebagai database utama untuk menyimpan data relasional seperti user, course, enrollment, content, comment, dan progress.
- Redis digunakan untuk caching data course, rate limiting, dan Celery result backend.
- MongoDB digunakan untuk menyimpan activity logs, learning analytics, dan course statistics.
- RabbitMQ digunakan sebagai message broker untuk mengirim task asynchronous dari Django API ke Celery Worker.
- Celery Worker digunakan untuk menjalankan task asynchronous seperti pengiriman email, generate certificate, update statistik course, dan export report.
- Celery Beat digunakan untuk menjalankan scheduled task secara berkala.
- Flower digunakan untuk monitoring Celery Worker dan queue RabbitMQ.

Alur utama sistem:

```text
Client / Swagger / Postman
        ↓
Django Ninja API
        ↓
PostgreSQL / Redis / MongoDB
        ↓
RabbitMQ
        ↓
Celery Worker
        ↓
Redis / MongoDB / PostgreSQL / Media Files
```

---

## 2. Flow Request API Umum

Alur umum ketika client mengakses API:

```text
1. Client mengirim HTTP request ke Django Ninja API.
2. Django Ninja API menerima request.
3. Jika endpoint membutuhkan autentikasi, sistem mengecek JWT access token.
4. Jika token valid, request dilanjutkan.
5. Jika endpoint membutuhkan authorization, sistem mengecek role user.
6. Django API menjalankan logic endpoint.
7. Data utama dibaca atau ditulis ke PostgreSQL.
8. Jika endpoint menggunakan Redis cache, sistem membaca atau menulis cache.
9. Jika endpoint menghasilkan log, sistem menyimpan activity log ke MongoDB.
10. Jika endpoint membutuhkan proses background, sistem mengirim task ke RabbitMQ.
11. API mengembalikan response ke client.
```

---

## 3. Flow Authentication

Authentication digunakan untuk memastikan bahwa user yang mengakses endpoint adalah user yang valid.

```text
1. User mengirim request login ke endpoint login.
2. Django API mengecek username dan password.
3. Jika username atau password salah, API mengembalikan error 401 Unauthorized.
4. Jika data login benar, API membuat access token dan refresh token.
5. Access token digunakan untuk mengakses endpoint protected.
6. Refresh token digunakan untuk mendapatkan access token baru ketika access token expired.
7. Token dikembalikan ke client.
8. Client menyimpan token dan mengirim access token pada header Authorization.
```

Format header:

```text
Authorization: Bearer <access_token>
```

---

## 4. Flow Authorization

Authorization digunakan untuk memastikan user hanya dapat melakukan aksi yang sesuai dengan role dan hak aksesnya.

```text
1. Client mengirim request ke endpoint protected.
2. Django API mengecek access token.
3. Jika token tidak valid atau tidak dikirim, API mengembalikan 401 Unauthorized.
4. Jika token valid, sistem mengambil data user dari token.
5. Sistem mengecek role user.
6. Role yang digunakan adalah Admin, Instructor, dan Student.
7. Jika user memiliki hak akses, request dilanjutkan.
8. Jika user tidak memiliki hak akses, API mengembalikan 403 Forbidden.
```

Contoh authorization pada course:

```text
1. Admin dapat mengakses dan mengelola semua course.
2. Instructor dapat membuat course.
3. Instructor hanya dapat mengubah course miliknya sendiri.
4. Student dapat melihat course dan melakukan enrollment.
```

---

## 5. Flow Course List Caching

Endpoint course list menggunakan Redis cache agar response lebih cepat dan query ke PostgreSQL berkurang.

Endpoint:

```text
GET /api/courses
```

Flow:

```text
1. Client mengirim request GET /api/courses.
2. Django API membuat cache key berdasarkan query parameter.
3. Query parameter dapat berupa search, price, page, page_size, dan ordering.
4. Django API mengecek apakah cache key tersebut tersedia di Redis.
5. Jika data ditemukan di Redis, API langsung mengembalikan data dari cache.
6. Jika data tidak ditemukan di Redis, API mengambil data dari PostgreSQL.
7. Data hasil query diproses sesuai filter, sorting, dan pagination.
8. Data hasil response disimpan ke Redis dengan TTL tertentu.
9. API mengembalikan response ke client.
```

Alur cache hit:

```text
Client request course list
        ↓
Django API cek Redis
        ↓
Data ditemukan
        ↓
Return data dari Redis
```

Alur cache miss:

```text
Client request course list
        ↓
Django API cek Redis
        ↓
Data tidak ditemukan
        ↓
Query ke PostgreSQL
        ↓
Simpan hasil ke Redis
        ↓
Return data ke client
```

---

## 6. Flow Course Detail Caching

Endpoint detail course menggunakan Redis cache agar detail course yang sering dibuka tidak selalu mengambil data dari PostgreSQL.

Endpoint:

```text
GET /api/courses/{course_id}
```

Flow:

```text
1. Client mengirim request detail course.
2. Django API membuat cache key berdasarkan course_id.
3. Django API mengecek Redis menggunakan cache key tersebut.
4. Jika data course tersedia di Redis, API mengembalikan data dari Redis.
5. Jika data tidak tersedia di Redis, API mengambil data course dari PostgreSQL.
6. Jika course tidak ditemukan di PostgreSQL, API mengembalikan 404 Not Found.
7. Jika course ditemukan, data disimpan ke Redis.
8. API mengembalikan detail course ke client.
```

---

## 7. Flow Cache Invalidation

Cache invalidation dilakukan untuk menghapus cache lama ketika data utama berubah.

Cache perlu dihapus pada proses:

```text
1. Create course
2. Update course
3. Delete course
4. Enroll course
```

Flow create course:

```text
1. Instructor atau admin mengirim request create course.
2. Django API melakukan validasi user.
3. Data course baru disimpan ke PostgreSQL.
4. Cache course list di Redis dihapus.
5. Activity log create course disimpan ke MongoDB.
6. API mengembalikan response course yang berhasil dibuat.
```

Flow update course:

```text
1. Instructor atau admin mengirim request update course.
2. Django API mengecek apakah course tersedia.
3. Django API mengecek apakah user berhak mengubah course tersebut.
4. Jika tidak berhak, API mengembalikan 403 Forbidden.
5. Jika berhak, data course diperbarui di PostgreSQL.
6. Cache detail course dihapus dari Redis.
7. Cache course list dihapus dari Redis.
8. Activity log update course disimpan ke MongoDB.
9. API mengembalikan response update berhasil.
```

Flow delete course:

```text
1. User mengirim request delete course.
2. Django API mengecek apakah course tersedia.
3. Django API mengecek apakah user memiliki hak untuk menghapus course.
4. Jika tidak berhak, API mengembalikan 403 Forbidden.
5. Jika berhak, data course dihapus dari PostgreSQL.
6. Cache detail course dihapus dari Redis.
7. Cache course list dihapus dari Redis.
8. Activity log delete course disimpan ke MongoDB.
9. API mengembalikan response delete berhasil.
```

---

## 8. Flow Rate Limiting

Rate limiting digunakan untuk membatasi jumlah request user dalam periode tertentu.

Batas request:

```text
60 requests / minute
```

Flow:

```text
1. Client mengirim request ke endpoint yang memiliki rate limit.
2. Django API membuat rate limit key berdasarkan user ID atau IP address.
3. Django API mengecek counter request di Redis.
4. Jika counter belum ada, Redis membuat counter baru dengan TTL 60 detik.
5. Setiap request akan menaikkan counter.
6. Jika jumlah request masih di bawah limit, request dilanjutkan.
7. Jika jumlah request melebihi limit, API mengembalikan 429 Too Many Requests.
```

Alur sukses:

```text
Request masuk
        ↓
Cek counter Redis
        ↓
Counter masih di bawah limit
        ↓
Lanjut proses endpoint
        ↓
Return response
```

Alur terkena limit:

```text
Request masuk
        ↓
Cek counter Redis
        ↓
Counter melebihi limit
        ↓
Return 429 Too Many Requests
```

---

## 9. Flow Activity Log MongoDB

MongoDB digunakan untuk menyimpan activity log karena log bersifat fleksibel dan tidak selalu memiliki struktur relasional yang kaku.

Collection:

```text
activity_logs
```

Flow:

```text
1. User melakukan aktivitas di API.
2. Django API menjalankan logic endpoint.
3. Setelah aktivitas berhasil, sistem membuat data log.
4. Data log berisi user_id, username, action, resource, resource_id, timestamp, dan metadata tambahan.
5. Data log disimpan ke collection activity_logs di MongoDB.
6. API tetap mengembalikan response utama ke client.
```

Contoh aktivitas yang dicatat:

```text
1. User register
2. User login
3. User refresh token
4. User membuat course
5. User mengubah course
6. User menghapus course
7. User enroll course
8. User menyelesaikan lesson
9. Sistem generate certificate
10. Sistem export report
```

---

## 10. Flow Learning Analytics MongoDB

Learning analytics digunakan untuk menyimpan aktivitas pembelajaran user.

Collection:

```text
learning_analytics
```

Flow:

```text
1. Student melakukan aktivitas pembelajaran.
2. Contohnya student enroll course atau menyelesaikan lesson.
3. Django API menyimpan data utama ke PostgreSQL.
4. Sistem membuat data analytics.
5. Data analytics disimpan ke MongoDB.
6. Data analytics dapat digunakan untuk laporan atau analisis progress belajar.
```

Contoh data analytics:

```text
1. Student enroll ke course tertentu.
2. Student menyelesaikan lesson.
3. Student menyelesaikan course.
4. Progress student bertambah.
5. Certificate berhasil dibuat.
```

---

## 11. Flow Course Statistics

Course statistics digunakan untuk menghitung ringkasan statistik course.

Collection:

```text
course_statistics
```

Flow:

```text
1. Sistem menjalankan task update_course_statistics.
2. Task dapat dijalankan secara manual melalui endpoint atau otomatis melalui Celery Beat.
3. Celery Worker mengambil data course dari PostgreSQL.
4. Celery Worker menghitung jumlah student yang enroll.
5. Celery Worker menghitung jumlah content dalam course.
6. Celery Worker menghitung jumlah progress atau completion.
7. Hasil statistik disimpan ke MongoDB.
8. Data statistik dapat digunakan untuk laporan course.
```

---

## 12. Flow Async Task dengan RabbitMQ dan Celery

Async task digunakan untuk menjalankan proses yang tidak harus selesai langsung dalam request utama.

Flow umum async task:

```text
1. Client mengirim request ke Django API.
2. Django API menjalankan proses utama.
3. Jika ada proses berat atau proses background, Django API membuat task.
4. Task dikirim ke RabbitMQ.
5. RabbitMQ menyimpan task dalam queue.
6. Celery Worker mengambil task dari RabbitMQ.
7. Celery Worker menjalankan task.
8. Hasil task disimpan ke Redis sebagai result backend.
9. Jika task menghasilkan log, Celery Worker menyimpan log ke MongoDB.
10. Jika task menghasilkan file, file disimpan ke media files.
11. Client dapat mengecek status task menggunakan task_id.
```

---

## 13. Flow send_enrollment_email

Task:

```text
send_enrollment_email
```

Tujuan:

```text
Mengirim email atau simulasi email ketika student berhasil enroll ke course.
```

Flow:

```text
1. Student mengirim request enroll course.
2. Django API mengecek apakah student sudah login.
3. Django API mengecek apakah course tersedia.
4. Django API mengecek apakah student sudah pernah enroll.
5. Jika belum pernah enroll, data enrollment disimpan ke PostgreSQL.
6. Cache course terkait dihapus dari Redis.
7. Activity log enroll disimpan ke MongoDB.
8. Django API mengirim task send_enrollment_email ke RabbitMQ.
9. RabbitMQ memasukkan task ke queue.
10. Celery Worker mengambil task dari RabbitMQ.
11. Celery Worker menjalankan proses pengiriman email atau simulasi email.
12. Hasil task disimpan ke Redis result backend.
13. Status task dapat dipantau melalui Flower.
```

---

## 14. Flow generate_certificate

Task:

```text
generate_certificate
```

Tujuan:

```text
Membuat certificate ketika student menyelesaikan course.
```

Flow:

```text
1. Student menyelesaikan lesson atau course.
2. Django API menyimpan progress ke PostgreSQL.
3. Sistem mengecek apakah seluruh lesson dalam course sudah selesai.
4. Jika course belum selesai, certificate tidak dibuat.
5. Jika course sudah selesai, Django API mengirim task generate_certificate ke RabbitMQ.
6. RabbitMQ menyimpan task ke queue.
7. Celery Worker mengambil task dari RabbitMQ.
8. Celery Worker mengambil data user dan course dari PostgreSQL.
9. Celery Worker membuat file certificate.
10. File certificate disimpan ke media files.
11. Activity log certificate_generated disimpan ke MongoDB.
12. Hasil task disimpan ke Redis result backend.
13. Status task dapat dilihat melalui endpoint task status atau Flower.
```

---

## 15. Flow update_course_statistics

Task:

```text
update_course_statistics
```

Tujuan:

```text
Menghitung dan memperbarui statistik course secara background.
```

Flow manual:

```text
1. Admin menjalankan endpoint update course statistics.
2. Django API mengecek authorization admin.
3. Django API mengirim task update_course_statistics ke RabbitMQ.
4. RabbitMQ menyimpan task ke queue.
5. Celery Worker mengambil task dari RabbitMQ.
6. Celery Worker mengambil data course dari PostgreSQL.
7. Celery Worker menghitung jumlah student, content, dan progress.
8. Celery Worker menyimpan hasil statistik ke MongoDB.
9. Hasil task disimpan ke Redis.
10. Admin dapat mengecek status task menggunakan task_id.
```

Flow scheduled:

```text
1. Celery Beat berjalan sebagai scheduler.
2. Pada interval tertentu, Celery Beat membuat task update_course_statistics.
3. Task dikirim ke RabbitMQ.
4. Celery Worker mengambil task dari queue.
5. Celery Worker menghitung statistik course.
6. Hasil statistik disimpan ke MongoDB.
7. Hasil task disimpan ke Redis.
```

---

## 16. Flow export_course_report

Task:

```text
export_course_report
```

Tujuan:

```text
Membuat laporan course dalam bentuk file CSV secara asynchronous.
```

Flow:

```text
1. Admin atau instructor mengirim request export report untuk course tertentu.
2. Django API mengecek autentikasi user.
3. Django API mengecek authorization user terhadap course tersebut.
4. Jika tidak memiliki akses, API mengembalikan 403 Forbidden.
5. Jika memiliki akses, Django API mengirim task export_course_report ke RabbitMQ.
6. RabbitMQ menyimpan task ke queue.
7. Celery Worker mengambil task dari RabbitMQ.
8. Celery Worker mengambil data course, student, enrollment, dan progress dari PostgreSQL.
9. Celery Worker membuat file CSV report.
10. File report disimpan ke media files.
11. Activity log export_course_report disimpan ke MongoDB.
12. Hasil task disimpan ke Redis result backend.
13. Client dapat mengecek status task menggunakan task_id.
14. Jika task selesai, path atau informasi file report dapat digunakan untuk mengakses hasil export.
```

---

## 17. Flow Task Status

Task status digunakan untuk mengecek status task asynchronous.

Flow:

```text
1. Client menjalankan endpoint yang menghasilkan task.
2. API mengembalikan task_id.
3. Client menyimpan task_id.
4. Client mengirim request cek status task berdasarkan task_id.
5. Django API mengecek status task dari Celery result backend di Redis.
6. Jika task masih berjalan, status yang dikembalikan adalah PENDING atau STARTED.
7. Jika task berhasil, status yang dikembalikan adalah SUCCESS.
8. Jika task gagal, status yang dikembalikan adalah FAILURE.
9. Response dikembalikan ke client.
```

Contoh status:

```text
PENDING  : task belum diproses
STARTED  : task sedang berjalan
SUCCESS  : task selesai
FAILURE  : task gagal
```

---

## 18. Flow Flower Monitoring

Flower digunakan untuk memantau Celery Worker dan task queue.

Flow:

```text
1. Flower dijalankan sebagai service di Docker Compose.
2. Flower terhubung ke RabbitMQ sebagai broker.
3. Flower membaca informasi queue dan worker.
4. Flower menampilkan daftar worker yang aktif.
5. Flower menampilkan daftar task yang sedang berjalan, berhasil, atau gagal.
6. Developer membuka Flower melalui browser.
7. Developer dapat memantau apakah Celery Worker berjalan normal.
```

Flower tidak menjalankan task utama. Flower hanya digunakan untuk monitoring.

---

## 19. Flow Docker Compose Services

Docker Compose menjalankan semua service yang dibutuhkan aplikasi.

Flow startup:

```text
1. Docker Compose menjalankan PostgreSQL.
2. Docker Compose menjalankan Redis.
3. Docker Compose menjalankan MongoDB.
4. Docker Compose menjalankan RabbitMQ.
5. Docker Compose menjalankan Django API.
6. Docker Compose menjalankan Celery Worker.
7. Docker Compose menjalankan Celery Beat.
8. Docker Compose menjalankan Flower.
9. Semua service berjalan dalam satu network Docker.
10. Django API dapat terhubung ke database, cache, broker, dan MongoDB menggunakan nama service.
```

Service utama:

```text
app             : Django Ninja API
database        : PostgreSQL
redis           : Redis cache, rate limit, result backend
mongodb         : MongoDB logs dan analytics
rabbitmq        : Message broker
celery-worker   : Worker untuk async task
celery-beat     : Scheduler untuk periodic task
flower          : Monitoring Celery
```

---

## 20. Flow Error Handling

Error handling digunakan agar API mengembalikan status code yang sesuai.

Flow umum:

```text
1. Client mengirim request.
2. Django API melakukan validasi.
3. Jika input tidak valid, API mengembalikan 400 Bad Request.
4. Jika user belum login atau token tidak valid, API mengembalikan 401 Unauthorized.
5. Jika user login tetapi tidak memiliki izin, API mengembalikan 403 Forbidden.
6. Jika data tidak ditemukan, API mengembalikan 404 Not Found.
7. Jika request melebihi rate limit, API mengembalikan 429 Too Many Requests.
8. Jika proses berhasil, API mengembalikan 200 OK atau 201 Created.
```

Ringkasan status code:

```text
200 OK                  : request berhasil
201 Created             : data berhasil dibuat
400 Bad Request         : input tidak valid
401 Unauthorized        : belum login atau token salah
403 Forbidden           : tidak memiliki hak akses
404 Not Found           : data tidak ditemukan
429 Too Many Requests   : request melebihi rate limit
500 Internal Error      : error server
```

---

## 21. Flow End-to-End Testing

Alur pengujian sistem dari awal sampai akhir:

```text
1. Jalankan semua service menggunakan Docker Compose.
2. Jalankan migration database.
3. Buat superuser.
4. Buka Swagger UI.
5. Register user baru.
6. Login user untuk mendapatkan access token.
7. Masukkan access token ke Swagger Authorization.
8. Buat course baru sebagai instructor atau admin.
9. Akses daftar course untuk menguji Redis cache.
10. Akses detail course untuk menguji Redis cache.
11. Update course untuk menguji cache invalidation.
12. Enroll student ke course untuk menguji enrollment flow.
13. Cek activity log di MongoDB.
14. Cek task send_enrollment_email di Flower.
15. Jalankan task update_course_statistics.
16. Cek hasil statistik di MongoDB.
17. Jalankan export_course_report.
18. Cek status task menggunakan task_id.
19. Cek hasil file report di media files.
20. Uji rate limiting dengan banyak request dalam satu menit.
```
