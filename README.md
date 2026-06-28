# Simple LMS — Backend API (MongoDB Analytics Enabled)

REST API untuk sistem Learning Management System (LMS) sederhana, dibangun dengan **Django 5**, **Django Ninja**, **PostgreSQL**, **Redis**, **MongoDB**, **Celery**, dan **RabbitMQ**.

Proyek ini menerapkan arsitektur **polyglot persistence**:
- **PostgreSQL** → Data transaksional utama (users, courses, enrollments) menggunakan Django ORM.
- **Redis** → Caching, session management, dan rate limiting.
- **MongoDB** → Analytics data, activity logs, dan HTTP request logs (skema fleksibel, performa tulis tinggi).

---

## Daftar Isi

- [Tech Stack](#tech-stack)
- [Arsitektur Database & Modeling](#arsitektur-database--modeling)
- [Cara Menjalankan Project](#cara-menjalankan-project)
- [Akun Demo](#akun-demo)
- [Dokumentasi API (Swagger)](#dokumentasi-api-swagger)
- [Daftar Endpoint](#daftar-endpoint)
- [Struktur Project](#struktur-project)

---

## Tech Stack

| Komponen | Teknologi | Keterangan |
|---|---|---|
| Framework | Django 5.1 + Django Ninja | REST API dengan validasi tipe data otomatis |
| Database Utama | PostgreSQL 16 | Data relasional transaksional utama |
| Cache & Rate Limiting | Redis 7 | Caching course list/detail & rate limit request |
| Message Broker | RabbitMQ 3 | Broker pesan untuk Celery |
| Task Queue | Celery 5 | Ekspor laporan async & generate sertifikat |
| Analytics & Logs | MongoDB 7 | Activity logs & auto HTTP request logs |
| Auth | JWT (PyJWT) | Autentikasi berbasis token stateless |
| Containerisasi | Docker + Docker Compose | Standarisasi deployment environment |

---

## Arsitektur Database & Modeling (MongoDB)

Proyek ini membagi MongoDB menjadi 2 database utama:
1. **`lms_analytics`** (untuk data analisis & progress):
   - `activity_logs`: Menggunakan model **Embedding** untuk metadata demi akses pembacaan yang cepat dalam satu dokumen tunggal.
   - `course_progress`: Menggunakan model **Referencing** (`user_id`, `course_id`) yang merujuk ke data master di PostgreSQL.
2. **`lms_logs`** (untuk log sistem & error):
   - `request_logs`: Menyimpan history hit HTTP request yang ditangkap secara otomatis.

### Indexing & Optimasi
Saat aplikasi startup, index berikut otomatis dibuat pada collection `activity_logs`:
- **Single field index**: `user_id`, `timestamp`, `action`
- **Compound index**: `(user_id, timestamp DESC)` dan `(action, timestamp DESC)`

---

## Cara Menjalankan Project

### Prasyarat
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) sudah terinstall dan berjalan.

### Langkah 1 — Salin konfigurasi environment

```bash
cp .env.example .env
```

> File `.env` sudah berisi nilai default untuk development termasuk `MONGODB_ANALYTICS_DB=lms_analytics`. Tidak perlu mengubah apapun untuk menjalankan secara lokal.

### Langkah 2 — Jalankan semua service

```bash
docker compose up -d
```

Docker akan menjalankan 8 service secara bersamaan:
- `lms-app` — Django API server (port **8000**)
- `lms-db` — PostgreSQL (port 5436)
- `lms-redis` — Redis (port 6379)
- `lms-mongodb` — MongoDB (port 27017)
- `lms-rabbitmq` — RabbitMQ + Management UI (port 5672 / **15672**)
- `lms-celery-worker` — Celery worker
- `lms-celery-beat` — Celery beat scheduler
- `lms-flower` — Celery monitoring UI (port **5555**)

### Langkah 3 — Isi data awal (seed)

Tunggu hingga container `lms-app` selesai menjalankan migrasi, lalu jalankan seeder:

```bash
docker compose exec app python manage.py seed_data
```

Seeder akan membuat:
- 3 Django Groups (Admin, Instructor, Student)
- 1 superuser admin
- 20 user dosen (Instructor) + 80 user mahasiswa (Student)
- 5 Kategori course
- 100 Course (dengan level, status, dan rating), 500 CourseMember, 300 CourseContent
- 92 CourseSection (kurikulum), 90 konten di-assign ke sections
- 213 CourseReview (dengan recalculated rating_avg), 200 Wishlist
- 1000+ Comment

### Langkah 4 — Verifikasi

| URL | Keterangan |
|---|---|
| http://localhost:8000/api/v1/docs | Swagger UI — dokumentasi & testing API (Termasuk modul `/analytics/`) |
| http://localhost:8000/admin/ | Django Admin panel |
| http://localhost:15672 | RabbitMQ Management (guest / guest) |
| http://localhost:5555 | Flower — Celery task monitoring |

---

## Akun Demo

Semua akun berikut langsung tersedia setelah menjalankan `seed_data`.

### Admin
| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Admin (Superuser) |

> Admin bisa mengakses Django Admin di `/admin/` dan semua endpoint yang dilindungi `require_admin`.

### Instructor (Dosen)
| Username | Password | Role |
|---|---|---|
| `dosen01` | `password123` | Instructor |
| `dosen02` | `password123` | Instructor |
| `dosen03` s/d `dosen20` | `password123` | Instructor |

> Instructor bisa membuat course, menambah lesson, upload file, dan export laporan.

### Student (Mahasiswa)
| Username | Password | Role |
|---|---|---|
| `mhs001` | `password123` | Student |
| `mhs002` | `password123` | Student |
| `mhs003` s/d `mhs080` | `password123` | Student |

> Student bisa melihat course, enroll, dan menandai lesson sebagai selesai.

---

## Dokumentasi API (Swagger)

Swagger UI tersedia di:

```
http://localhost:8000/api/v1/docs
```

Untuk mengakses endpoint yang membutuhkan autentikasi:
1. Panggil `POST /api/v1/auth/login` dengan username dan password akun demo.
2. Salin nilai `access` dari response.
3. Klik tombol **Authorize** di Swagger UI.
4. Masukkan: `Bearer <access_token>`

---

## Daftar Endpoint

Semua endpoint berada di bawah prefix `/api/v1/`.

### 🔐 Authentication

| Method | Endpoint | Auth | Deskripsi |
|---|---|---|---|
| `POST` | `/auth/register` | ❌ | Daftar akun baru (otomatis jadi Student) |
| `POST` | `/auth/login` | ❌ | Login, mendapatkan access & refresh token |
| `POST` | `/auth/refresh` | ❌ | Perbarui access token menggunakan refresh token |
| `GET` | `/auth/me` | ✅ | Lihat profil user yang sedang login |
| `PUT` | `/auth/me` | ✅ | Update profil (email, nama) |

### 📁 Categories

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `GET` | `/categories` | ❌ | Semua | List semua kategori |
| `GET` | `/categories/{id}` | ❌ | Semua | Detail satu kategori |
| `POST` | `/categories` | ✅ | Admin | Buat kategori baru |
| `PATCH` | `/categories/{id}` | ✅ | Admin | Update kategori |
| `DELETE` | `/categories/{id}` | ✅ | Admin | Hapus kategori |
| `GET` | `/categories/{id}/courses` | ❌ | Semua | List semua course dalam kategori |

### 📚 Courses

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `GET` | `/courses` | ❌ | Semua | List semua course (support filter & pagination) |
| `GET` | `/courses/{id}` | ❌ | Semua | Detail satu course |
| `POST` | `/courses` | ✅ | Instructor | Buat course baru |
| `PATCH` | `/courses/{id}` | ✅ | Owner/Admin | Update course |
| `DELETE` | `/courses/{id}` | ✅ | Owner/Admin | Hapus course |

**Query parameter untuk `GET /courses`:**
- `search` — cari berdasarkan nama/deskripsi
- `category_id` — filter berdasarkan ID kategori
- `instructor_id` — filter berdasarkan ID instructor
- `level` — filter level (`beginner`, `intermediate`, `advanced`)
- `status` — filter status (`draft`, `published`, `archived`)
- `min_price` / `max_price` — filter harga
- `ordering` — urutan (`name`, `-name`, `price`, `-price`, `created_at`, `-created_at`, `rating_avg`, `-rating_avg`)
- `page` / `page_size` — pagination

### 📄 Contents (Lesson)

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `GET` | `/courses/{id}/contents` | ❌ | Semua | List semua lesson dalam course |
| `GET` | `/courses/{id}/contents/{id}` | ❌ | Semua | Detail satu lesson |
| `POST` | `/courses/{id}/contents` | ✅ | Owner/Admin | Tambah lesson baru ke course |
| `PATCH` | `/courses/{id}/contents/{id}` | ✅ | Owner/Admin | Update lesson |
| `DELETE` | `/courses/{id}/contents/{id}` | ✅ | Owner/Admin | Hapus lesson |

### 📚 Sections (Kurikulum)

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `GET` | `/courses/{id}/sections` | ❌ | Semua | List sections beserta lessons di dalamnya |
| `POST` | `/courses/{id}/sections` | ✅ | Owner/Admin | Buat section baru |
| `PATCH` | `/courses/{id}/sections/{section_id}` | ✅ | Owner/Admin | Update section |
| `DELETE` | `/courses/{id}/sections/{section_id}` | ✅ | Owner/Admin | Hapus section |

### ⭐ Reviews

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `GET` | `/courses/{id}/reviews` | ❌ | Semua | List semua review + rating_avg |
| `POST` | `/courses/{id}/reviews` | ✅ | Student (enrolled) | Buat atau update review |
| `DELETE` | `/courses/{id}/reviews/{review_id}` | ✅ | Owner/Admin | Hapus review |

> Rating otomatis dihitung ulang (1–5 bintang) dan disimpan di field `rating_avg` course setiap kali review dibuat/dihapus.

### ❤️ Wishlist

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `GET` | `/wishlist` | ✅ | Login | Lihat semua course di wishlist |
| `POST` | `/wishlist` | ✅ | Login | Tambah course ke wishlist |
| `DELETE` | `/wishlist/{course_id}` | ✅ | Login | Hapus course dari wishlist |

### 🎓 Enrollments & Progress

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `POST` | `/enrollments` | ✅ | Student | Enroll ke sebuah course |
| `GET` | `/enrollments/my-courses` | ✅ | Student | Lihat semua course yang diikuti |
| `POST` | `/enrollments/{id}/progress` | ✅ | Student | Tandai lesson sebagai selesai |
| `GET` | `/enrollments/{id}/progress` | ✅ | Student/Admin | Progress detail per section + persentase |

### 📊 Student Dashboard

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `GET` | `/dashboard/student` | ✅ | Login | Dashboard student: course aktif, selesai, wishlist, rekomendasi |

### 📎 File Upload / Download

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `POST` | `/courses/{id}/content/{id}/upload` | ✅ | Owner/Admin | Upload file ke lesson |
| `GET` | `/courses/{id}/content/{id}/download` | ✅ | Member/Owner/Admin | Download file dari lesson |

> Format file yang diizinkan: `.pdf`, `.doc`, `.docx`, `.ppt`, `.pptx`, `.mp4`, `.png`, `.jpg`, `.jpeg`. Ukuran maksimal: **10 MB**.

### ⚙️ Async Tasks (Celery)

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `POST` | `/courses/{id}/export-report` | ✅ | Owner/Admin | Request ekspor laporan course (async) |
| `POST` | `/tasks/update-course-statistics` | ✅ | Admin | Jalankan update statistik course |
| `GET` | `/tasks/{task_id}` | ✅ | Login | Cek status task Celery |

### 📊 Reports & Legacy Logs (MongoDB)

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `GET` | `/reports/activity` | ✅ | Admin | Laporan aktivitas user dari MongoDB (`lms_logs`) |
| `GET` | `/reports/learning` | ✅ | Admin | Laporan aktivitas belajar dari MongoDB (`lms_logs`) |

### 📈 Analytics (MongoDB lms_analytics — NEW Chapter 11)

Semua endpoint analytics baru di-mount di bawah path `/api/v1/analytics/`.

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `POST` | `/analytics/log/` | ✅ | Semua | Mencatat aktivitas custom secara manual ke MongoDB |
| `GET` | `/analytics/popular-courses/` | ❌ | Semua | Menampilkan 10 kursus terpopuler berdasarkan total views |
| `GET` | `/analytics/user/{user_id}/summary/` | ✅ | Semua | Menampilkan ringkasan total dan waktu aktivitas per user |
| `GET` | `/analytics/daily-summary/` | ✅ | Semua | Menampilkan time-series harian total log & user unik |

#### Auto Activity Logging Middleware
Setiap HTTP request ke API secara otomatis terekam ke MongoDB `request_logs` secara asinkron menggunakan daemon thread tanpa menghambat response time API ke user.

---

## Struktur Project

```
BE-Simple-LMS/
├── .env                    # Konfigurasi environment (tidak di-commit)
├── .env.example            # Template konfigurasi (di-commit)
├── .gitignore
├── docker-compose.yml      # Orkestrasi semua service
├── BASELINE_README.md      # Catatan baseline project awal
├── README.md               # File petunjuk ini
└── code/                   # Source code Django
    ├── manage.py
    ├── requirements.txt
    ├── lms/                # Konfigurasi Django project
    │   ├── settings.py
    │   ├── urls.py
    │   └── celery.py
    ├── courses/            # Aplikasi utama (PostgreSQL + Redis + Celery)
    │   ├── models.py
    │   ├── api.py
    │   ├── schemas.py
    │   └── ...
    └── analytics/          # Aplikasi Analytics (MongoDB - Chapter 11)
        ├── apps.py         # Inisialisasi index MongoDB saat startup
        ├── mongo_service.py# Pymongo singleton, CRUD & Aggregation Pipeline
        ├── api.py          # Endpoint analytics Django Ninja
        ├── middleware.py   # Auto-logging HTTP requests di background thread
        ├── tests.py        # Unit tests dengan mock MongoDB
        └── urls.py         # Routing placeholder
```
