# Simple LMS — Backend API

REST API untuk sistem Learning Management System (LMS) sederhana, dibangun dengan **Django 5**, **Django Ninja**, **PostgreSQL**, **Redis**, **MongoDB**, **Celery**, dan **RabbitMQ**.

---

## Daftar Isi

- [Tech Stack](#tech-stack)
- [Cara Menjalankan Project](#cara-menjalankan-project)
- [Akun Demo](#akun-demo)
- [Dokumentasi API (Swagger)](#dokumentasi-api-swagger)
- [Daftar Endpoint](#daftar-endpoint)
- [Struktur Project](#struktur-project)

---

## Tech Stack

| Komponen | Teknologi |
|---|---|
| Framework | Django 5.1 + Django Ninja |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| Message Broker | RabbitMQ 3 |
| Task Queue | Celery 5 |
| Activity Log | MongoDB 7 |
| Auth | JWT (PyJWT) |
| Containerisasi | Docker + Docker Compose |

---

## Cara Menjalankan Project

### Prasyarat
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) sudah terinstall dan berjalan

### Langkah 1 — Salin konfigurasi environment

```bash
cp .env.example .env
```

> File `.env` sudah berisi nilai default untuk development. Tidak perlu mengubah apapun untuk menjalankan secara lokal.

### Langkah 2 — Jalankan semua service

```bash
docker compose up -d
```

Docker akan menjalankan 7 service secara bersamaan:
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
- 20 user dosen (Instructor)
- 80 user mahasiswa (Student)
- 100 Course, 500 CourseMember, 300 CourseContent, 1000+ Comment

### Langkah 4 — Verifikasi

| URL | Keterangan |
|---|---|
| http://localhost:8000/api/v1/docs | Swagger UI — dokumentasi & testing API |
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
1. Panggil `POST /api/v1/auth/login` dengan username dan password akun demo
2. Salin nilai `access` dari response
3. Klik tombol **Authorize** di Swagger UI
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
- `instructor_id` — filter berdasarkan ID instructor
- `min_price` / `max_price` — filter harga
- `ordering` — urutan (`name`, `-name`, `price`, `-price`, `created_at`, `-created_at`)
- `page` / `page_size` — pagination

### 📄 Contents (Lesson)

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `GET` | `/courses/{id}/contents` | ❌ | Semua | List semua lesson dalam course |
| `GET` | `/courses/{id}/contents/{id}` | ❌ | Semua | Detail satu lesson |
| `POST` | `/courses/{id}/contents` | ✅ | Owner/Admin | Tambah lesson baru ke course |
| `PATCH` | `/courses/{id}/contents/{id}` | ✅ | Owner/Admin | Update lesson |
| `DELETE` | `/courses/{id}/contents/{id}` | ✅ | Owner/Admin | Hapus lesson |

### 🎓 Enrollments & Progress

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `POST` | `/enrollments` | ✅ | Student | Enroll ke sebuah course |
| `GET` | `/enrollments/my-courses` | ✅ | Student | Lihat semua course yang diikuti |
| `POST` | `/enrollments/{id}/progress` | ✅ | Student | Tandai lesson sebagai selesai |

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

### 📊 Reports (MongoDB)

| Method | Endpoint | Auth | Role | Deskripsi |
|---|---|---|---|---|
| `GET` | `/reports/activity` | ✅ | Admin | Laporan aktivitas user dari MongoDB |
| `GET` | `/reports/learning` | ✅ | Admin | Laporan aktivitas belajar dari MongoDB |

---

## Struktur Project

```
BE-Simple-LMS/
├── .env                    # Konfigurasi environment (tidak di-commit)
├── .env.example            # Template konfigurasi (di-commit)
├── .gitignore
├── docker-compose.yml      # Orkestrasi semua service
├── BASELINE_README.md      # File ini
└── code/                   # Source code Django
    ├── manage.py
    ├── requirements.txt
    ├── lms/                # Konfigurasi Django project
    │   ├── settings.py
    │   ├── urls.py
    │   └── celery.py
    └── courses/            # Aplikasi utama
        ├── models.py       # Model: Category, Course, CourseMember, CourseContent, LessonProgress
        ├── api.py          # Semua endpoint Django Ninja
        ├── schemas.py      # Pydantic schema input/output
        ├── auth.py         # JWT authentication
        ├── permissions.py  # RBAC: require_admin, require_instructor, require_student
        ├── cache.py        # Redis cache helpers
        ├── rate_limit.py   # Rate limiting via Redis
        ├── mongo.py        # MongoDB activity logging
        ├── tasks.py        # Celery async tasks
        └── management/
            └── commands/
                └── seed_data.py  # Management command untuk data awal
```
