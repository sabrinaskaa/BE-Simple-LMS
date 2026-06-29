import random
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, User
from django.db.models import Avg, Count
from courses.models import (
    Category, Course, CourseMember, CourseContent, CourseReview,
    CourseSection, Comment, LessonProgress, Wishlist,
)


# =============================================================================
# Kamus data Indonesia untuk menghasilkan konten yang realistis
# =============================================================================

FIRST_NAMES = [
    'Budi', 'Siti', 'Ahmad', 'Dewi', 'Reza',
    'Putri', 'Andi', 'Rina', 'Hendra', 'Yuli',
    'Fajar', 'Nisa', 'Dimas', 'Ayu', 'Rizki',
    'Lestari', 'Wahyu', 'Maya', 'Bagas', 'Citra',
]

LAST_NAMES = [
    'Santoso', 'Wijaya', 'Kusuma', 'Rahayu', 'Pratama',
    'Sari', 'Hidayat', 'Permata', 'Nugroho', 'Lestari',
    'Wibowo', 'Mahendra', 'Putra', 'Dewi', 'Susanto',
    'Kurniawan', 'Handoko', 'Utama', 'Saputra', 'Prabowo',
]

SUBJECTS = [
    'Pemrograman Web',
    'Basis Data',
    'Algoritma dan Struktur Data',
    'Jaringan Komputer',
    'Sistem Operasi',
    'Kecerdasan Buatan',
    'Pemrograman Mobile',
    'Keamanan Siber',
    'Rekayasa Perangkat Lunak',
    'Pemrograman Python',
    'Pemrograman Java',
    'Manajemen Proyek TI',
    'Analisis dan Desain Sistem',
    'Komputasi Awan',
    'Data Mining',
    'Statistika',
    'Matematika Diskrit',
    'Arsitektur Komputer',
    'Grafika Komputer',
    'Interaksi Manusia Komputer',
]

CONTENT_PREFIXES = [
    'Pengantar',
    'Konsep Dasar',
    'Praktikum',
    'Latihan',
    'Kuis',
    'Modul',
    'Materi',
    'Diskusi',
    'Proyek',
    'Tugas',
]

CONTENT_TOPICS = [
    'Variabel dan Tipe Data',
    'Struktur Kontrol',
    'Fungsi dan Prosedur',
    'Array dan List',
    'Object Oriented Programming',
    'Database Design',
    'Query SQL',
    'Normalisasi Database',
    'REST API',
    'Autentikasi dan Otorisasi',
    'Deployment Aplikasi',
    'Unit Testing',
    'Debugging dan Profiling',
    'Optimasi Kode',
    'Git dan Version Control',
    'Docker dan Containerisasi',
    'Arsitektur Microservices',
    'Design Pattern',
    'Clean Code',
    'Dokumentasi API',
]

COMMENTS = [
    'Materi ini sangat membantu, terima kasih!',
    'Apakah ada referensi tambahan untuk topik ini?',
    'Saya belum paham bagian ini, bisa dijelaskan lagi?',
    'Keren sekali materinya, langsung saya coba praktikkan.',
    'Tugas ini cukup menantang tapi sangat bermanfaat!',
    'Mohon bantuannya untuk soal ini, sudah dicoba tapi masih bingung.',
    'Sudah dicoba tapi masih error, kira-kira kenapa ya?',
    'Terima kasih penjelasannya, sekarang sudah lebih jelas.',
    'Apakah boleh menggunakan library lain selain yang disebutkan?',
    'Saya setuju dengan pendapat teman di atas.',
    'Kapan deadline pengumpulan tugasnya?',
    'Boleh minta contoh kode yang sudah selesai sebagai referensi?',
    'Bagian ini yang paling susah menurut saya, perlu penjelasan lebih.',
    'Alhamdulillah, sudah berhasil mengerjakan!',
    'Materinya sangat relevan dengan kebutuhan industri saat ini.',
    'Apakah ada video penjelasan tambahan untuk materi ini?',
    'Terima kasih atas feedback-nya, sangat membantu perbaikan.',
    'Sudah saya coba ulang dan berhasil, terima kasih!',
    'Materinya padat dan informatif, suka sekali gaya penjelasannya.',
    'Ada yang bisa bantu explain perbedaannya dengan konsep sebelumnya?',
]

REVIEW_TEXTS = [
    'Materi sangat lengkap dan mudah dipahami. Sangat direkomendasikan!',
    'Instruktur menjelaskan dengan sangat jelas dan sabar.',
    'Course yang bagus untuk pemula, step by step sangat terstruktur.',
    'Kurang update dengan teknologi terbaru, tapi dasarnya bagus.',
    'Sangat membantu karir saya, langsung bisa dipraktikkan.',
    'Penjelasan terlalu cepat di beberapa bagian.',
    'Konten berkualitas tinggi, worth every penny!',
    'Latihan soal sangat membantu pemahaman materi.',
    'Perlu lebih banyak contoh kasus nyata.',
    'Instruktur sangat responsif menjawab pertanyaan.',
    'Struktur kursus yang baik, dari dasar hingga lanjutan.',
    'Banyak ilmu baru yang saya dapatkan dari sini.',
    'Rekomendasikan untuk siapa saja yang ingin belajar dari nol.',
    'Video berkualitas baik dan audio jelas.',
    'Beberapa materi bisa lebih diperdalam.',
]

SECTION_TITLES = [
    'Pendahuluan',
    'Materi Dasar',
    'Konsep Inti',
    'Praktik Langsung',
    'Studi Kasus',
    'Proyek Akhir',
    'Evaluasi dan Kuis',
    'Materi Lanjutan',
    'Tips dan Trik',
    'Penutup dan Ringkasan',
]

PRICES = [50000, 75000, 100000, 125000, 150000, 200000, 250000]
LEVELS = ['beginner', 'intermediate', 'advanced']
STATUSES = ['draft', 'published', 'published', 'published', 'archived']  # lebih banyak published


class Command(BaseCommand):
    help = 'Seed database dengan data dummy untuk LMS'

    def handle(self, *args, **options):
        # Seed random agar hasil konsisten setiap kali dijalankan
        random.seed(42)

        self.stdout.write(self.style.HTTP_INFO('=' * 55))
        self.stdout.write(self.style.HTTP_INFO('  Seeding Data - Simple LMS'))
        self.stdout.write(self.style.HTTP_INFO('=' * 55))

        groups = self._seed_groups()
        teachers = self._seed_teachers(groups['instructor'])
        students = self._seed_students(groups['student'])
        self._seed_categories()
        courses = self._seed_courses(teachers)
        members = self._seed_members(courses, students)
        contents = self._seed_contents(courses)
        self._seed_sections(courses, contents)
        self._seed_comments(contents, members)
        self._seed_reviews(courses, members, students)
        self._seed_wishlist(courses, students)
        self._seed_lesson_progress(members, contents)

        self._print_summary()

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Seeding selesai! Sekarang coba:'))
        self.stdout.write('  http://localhost:8000/api/v1/docs       ← Swagger UI')
        self.stdout.write('  http://localhost:8000/admin/            ← manajemen data')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Akun demo yang tersedia:'))
        self.stdout.write('  Admin     : admin / admin123')
        self.stdout.write('  Instructor: dosen01 - dosen20 / password123')
        self.stdout.write('  Student   : mhs001 - mhs080 / password123')

    # -------------------------------------------------------------------------
    # Step 0: Buat Django Groups untuk RBAC (Admin, Instructor, Student)
    # -------------------------------------------------------------------------
    def _seed_groups(self):
        self.stdout.write('\n[0/9] Membuat Django Groups (Admin, Instructor, Student)...')

        admin_group, admin_created = Group.objects.get_or_create(name='Admin')
        instructor_group, instructor_created = Group.objects.get_or_create(name='Instructor')
        student_group, student_created = Group.objects.get_or_create(name='Student')

        if not User.objects.filter(username='admin').exists():
            admin_user = User.objects.create_superuser(
                username='admin',
                email='admin@lms.ac.id',
                password='admin123',
                first_name='Super',
                last_name='Admin',
            )
            admin_user.groups.add(admin_group)
            self.stdout.write('  → Superuser "admin" dibuat (password: admin123)')
        else:
            self.stdout.write('  → Superuser "admin" sudah ada (skip)')

        statuses = [
            f'Admin({"baru" if admin_created else "sudah ada"})',
            f'Instructor({"baru" if instructor_created else "sudah ada"})',
            f'Student({"baru" if student_created else "sudah ada"})',
        ]
        self.stdout.write(f'  → Groups: {", ".join(statuses)}')

        return {
            'admin': admin_group,
            'instructor': instructor_group,
            'student': student_group,
        }

    # -------------------------------------------------------------------------
    # Step 1: Buat 20 User pengajar
    # -------------------------------------------------------------------------
    def _seed_teachers(self, instructor_group):
        self.stdout.write('\n[1/9] Membuat pengajar (dosen01 - dosen20)...')

        existing = set(
            User.objects.filter(username__startswith='dosen')
            .values_list('username', flat=True)
        )

        to_create = []
        for i in range(1, 21):
            username = f'dosen{i:02d}'
            if username not in existing:
                fname = FIRST_NAMES[(i - 1) % len(FIRST_NAMES)]
                lname = LAST_NAMES[(i - 1) % len(LAST_NAMES)]
                to_create.append(User(
                    username=username,
                    first_name=fname,
                    last_name=lname,
                    email=f'{username}@univ.ac.id',
                    is_staff=False,
                    password=make_password('password123'),
                ))

        if to_create:
            User.objects.bulk_create(to_create, ignore_conflicts=True)

        teachers = list(User.objects.filter(username__startswith='dosen'))

        already_in_group = set(
            instructor_group.user_set.filter(username__startswith='dosen')
            .values_list('id', flat=True)
        )
        to_assign = [t for t in teachers if t.id not in already_in_group]
        if to_assign:
            instructor_group.user_set.add(*to_assign)
            self.stdout.write(f'  → {len(to_assign)} dosen di-assign ke group "Instructor"')

        self.stdout.write(f'  → {len(teachers)} pengajar tersedia')
        return teachers

    # -------------------------------------------------------------------------
    # Step 2: Buat 80 User mahasiswa
    # -------------------------------------------------------------------------
    def _seed_students(self, student_group):
        self.stdout.write('\n[2/9] Membuat mahasiswa (mhs001 - mhs080)...')

        existing = set(
            User.objects.filter(username__startswith='mhs')
            .values_list('username', flat=True)
        )

        to_create = []
        for i in range(1, 81):
            username = f'mhs{i:03d}'
            if username not in existing:
                to_create.append(User(
                    username=username,
                    first_name=random.choice(FIRST_NAMES),
                    last_name=random.choice(LAST_NAMES),
                    email=f'{username}@student.univ.ac.id',
                    password=make_password('password123'),
                ))

        if to_create:
            User.objects.bulk_create(to_create, ignore_conflicts=True)

        students = list(User.objects.filter(username__startswith='mhs'))

        already_in_group = set(
            student_group.user_set.filter(username__startswith='mhs')
            .values_list('id', flat=True)
        )
        to_assign = [s for s in students if s.id not in already_in_group]
        if to_assign:
            student_group.user_set.add(*to_assign)
            self.stdout.write(f'  → {len(to_assign)} mahasiswa di-assign ke group "Student"')

        self.stdout.write(f'  → {len(students)} mahasiswa tersedia')
        return students

    # -------------------------------------------------------------------------
    # Step 2.5: Buat Categories
    # -------------------------------------------------------------------------
    def _seed_categories(self):
        self.stdout.write('\n[2.5/9] Membuat kategori course...')
        CATEGORIES = [
            ('Pemrograman', 'Kursus tentang bahasa pemrograman dan pengembangan software'),
            ('Basis Data', 'Kursus manajemen dan desain database'),
            ('Jaringan & Keamanan', 'Kursus jaringan komputer dan keamanan siber'),
            ('Data Science', 'Kursus analisis data, machine learning, dan AI'),
            ('DevOps & Cloud', 'Kursus deployment, containerisasi, dan cloud computing'),
        ]
        for name, desc in CATEGORIES:
            Category.objects.get_or_create(name=name, defaults={'description': desc})
        self.stdout.write(f'  → {Category.objects.count()} kategori tersedia')

    # -------------------------------------------------------------------------
    # Step 3: Buat 100 Course
    # -------------------------------------------------------------------------
    def _seed_courses(self, teachers):
        self.stdout.write('\n[3/9] Membuat 100 mata kuliah...')

        categories = list(Category.objects.all())
        existing_count = Course.objects.count()
        to_create = []

        for i in range(existing_count, 100):
            subject = SUBJECTS[i % len(SUBJECTS)]
            kelas_idx = i // len(SUBJECTS)
            name = subject if kelas_idx == 0 else f'{subject} - Kelas {chr(65 + kelas_idx - 1)}'
            to_create.append(Course(
                name=name,
                description=(
                    f'Mata kuliah {subject} membahas konsep dasar hingga lanjutan '
                    f'dengan pendekatan teori dan praktikum. Mahasiswa akan mampu '
                    f'menerapkan ilmu ini di dunia kerja.'
                ),
                price=random.choice(PRICES),
                teacher=random.choice(teachers),
                level=random.choice(LEVELS),
                status=random.choice(STATUSES),
                category=random.choice(categories) if categories else None,
            ))

        if to_create:
            Course.objects.bulk_create(to_create, batch_size=500)

        courses = list(Course.objects.all()[:100])
        self.stdout.write(f'  → {Course.objects.count()} mata kuliah tersedia')
        return courses

    # -------------------------------------------------------------------------
    # Step 4: Buat 500 CourseMember
    # -------------------------------------------------------------------------
    def _seed_members(self, courses, students):
        self.stdout.write('\n[4/9] Membuat 500 anggota kelas...')

        existing_count = CourseMember.objects.count()
        existing_pairs = set(
            CourseMember.objects.values_list('course_id_id', 'user_id_id')
        )

        to_create = []
        attempts = 0
        target = 500 - existing_count

        while len(to_create) < target and attempts < 10000:
            attempts += 1
            course = random.choice(courses)
            student = random.choice(students)
            pair = (course.id, student.id)

            if pair not in existing_pairs:
                existing_pairs.add(pair)
                role = 'ast' if random.random() < 0.1 else 'std'
                to_create.append(CourseMember(
                    course_id=course,
                    user_id=student,
                    roles=role,
                ))

        if to_create:
            CourseMember.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)

        members = list(CourseMember.objects.all())
        self.stdout.write(f'  → {CourseMember.objects.count()} anggota kelas tersedia')
        return members

    # -------------------------------------------------------------------------
    # Step 5: Buat 300 CourseContent
    # -------------------------------------------------------------------------
    def _seed_contents(self, courses):
        self.stdout.write('\n[5/9] Membuat 300 konten kelas...')

        existing_count = CourseContent.objects.count()
        to_create = []

        for i in range(existing_count, 300):
            course = courses[i % len(courses)]
            prefix = CONTENT_PREFIXES[i % len(CONTENT_PREFIXES)]
            topic = random.choice(CONTENT_TOPICS)
            to_create.append(CourseContent(
                name=f'{prefix} {topic}',
                description=(
                    f'Materi {prefix.lower()} mengenai {topic.lower()} '
                    f'dalam konteks {course.name}. '
                    f'Pelajari konsep ini dengan seksama sebelum mengerjakan latihan.'
                ),
                course_id=course,
                parent_id=None,
                order=i % 10,
                duration_minutes=random.choice([15, 20, 30, 45, 60, None]),
            ))

        if to_create:
            CourseContent.objects.bulk_create(to_create, batch_size=500)

        contents = list(CourseContent.objects.all()[:300])
        self.stdout.write(f'  → {CourseContent.objects.count()} konten tersedia')
        return contents

    # -------------------------------------------------------------------------
    # Step 6: Buat Sections dan assign contents ke sections
    # -------------------------------------------------------------------------
    def _seed_sections(self, courses, contents):
        self.stdout.write('\n[6/9] Membuat sections dan mengorganisir konten...')

        if CourseSection.objects.count() > 0:
            self.stdout.write(f'  → {CourseSection.objects.count()} sections sudah ada (skip)')
            return

        sections_to_create = []
        # Buat 2-3 sections untuk setiap course (dari 30 course pertama saja agar tidak terlalu banyak)
        sample_courses = courses[:30]
        for course in sample_courses:
            num_sections = random.randint(2, 4)
            for j in range(num_sections):
                sections_to_create.append(CourseSection(
                    course=course,
                    title=SECTION_TITLES[j % len(SECTION_TITLES)],
                    order=j,
                ))

        CourseSection.objects.bulk_create(sections_to_create, batch_size=500)

        # Assign sebagian contents ke sections secara random
        all_sections = list(CourseSection.objects.all())
        if not all_sections:
            return

        # Ambil contents yang belum punya section
        unassigned = list(CourseContent.objects.filter(section__isnull=True)[:150])
        to_update = []
        for i, content in enumerate(unassigned):
            section = all_sections[i % len(all_sections)]
            # Pastikan section dari course yang sama
            course_sections = [s for s in all_sections if s.course_id == content.course_id_id]
            if course_sections:
                content.section = random.choice(course_sections)
                content.order = i % 10
                to_update.append(content)

        if to_update:
            CourseContent.objects.bulk_update(to_update, ['section', 'order'], batch_size=200)

        self.stdout.write(f'  → {CourseSection.objects.count()} sections dibuat')
        self.stdout.write(f'  → {len(to_update)} konten di-assign ke sections')

    # -------------------------------------------------------------------------
    # Step 7: Buat 1000+ Comment
    # -------------------------------------------------------------------------
    def _seed_comments(self, contents, members):
        self.stdout.write('\n[7/9] Membuat 1000+ komentar...')

        existing_count = Comment.objects.count()
        target = 1000 - existing_count

        if target <= 0:
            self.stdout.write(f'  → {Comment.objects.count()} komentar tersedia (skip)')
            return

        members_by_course = {}
        for member in members:
            cid = member.course_id_id
            if cid not in members_by_course:
                members_by_course[cid] = []
            members_by_course[cid].append(member)

        to_create = []
        fallback_members = members[:20]

        for _ in range(target):
            content = random.choice(contents)
            course_members = members_by_course.get(content.course_id_id, fallback_members)
            member = random.choice(course_members)
            to_create.append(Comment(
                content_id=content,
                member_id=member,
                comment=random.choice(COMMENTS),
            ))

        Comment.objects.bulk_create(to_create, batch_size=500)
        self.stdout.write(f'  → {Comment.objects.count()} komentar tersedia')

    # -------------------------------------------------------------------------
    # Step 8: Buat Reviews
    # -------------------------------------------------------------------------
    def _seed_reviews(self, courses, members, students):
        self.stdout.write('\n[8/9] Membuat reviews course...')

        if CourseReview.objects.count() > 0:
            self.stdout.write(f'  → {CourseReview.objects.count()} reviews sudah ada (skip)')
            return

        # Build set pasangan (course_id, user_id) yang sudah enroll
        enrolled_pairs = {
            (m.course_id_id, m.user_id_id): m for m in members
        }

        to_create = []
        created_pairs = set()
        target = 300

        attempts = 0
        while len(to_create) < target and attempts < 5000:
            attempts += 1
            course = random.choice(courses)
            student = random.choice(students)
            pair = (course.id, student.id)

            # Hanya buat review jika student sudah enroll dan belum review
            if pair in enrolled_pairs and pair not in created_pairs:
                created_pairs.add(pair)
                to_create.append(CourseReview(
                    course=course,
                    user=student,
                    rating=random.choices([1, 2, 3, 4, 5], weights=[5, 10, 20, 35, 30])[0],
                    review=random.choice(REVIEW_TEXTS) if random.random() > 0.3 else '',
                ))

        CourseReview.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)

        # Recalculate rating_avg dan total_reviews untuk setiap course
        reviews_agg = (
            CourseReview.objects
            .values('course_id')
            .annotate(avg=Avg('rating'), total=Count('id'))
        )
        to_update = []
        agg_map = {r['course_id']: r for r in reviews_agg}
        for course in courses:
            if course.id in agg_map:
                course.rating_avg = round(agg_map[course.id]['avg'] or 0, 2)
                course.total_reviews = agg_map[course.id]['total']
                to_update.append(course)

        if to_update:
            Course.objects.bulk_update(to_update, ['rating_avg', 'total_reviews'], batch_size=200)

        self.stdout.write(f'  → {CourseReview.objects.count()} reviews dibuat')

    # -------------------------------------------------------------------------
    # Step 9: Buat Wishlist
    # -------------------------------------------------------------------------
    def _seed_wishlist(self, courses, students):
        self.stdout.write('\n[9/9] Membuat wishlist...')

        if Wishlist.objects.count() > 0:
            self.stdout.write(f'  → {Wishlist.objects.count()} wishlist sudah ada (skip)')
            return

        to_create = []
        created_pairs = set()
        target = 200

        attempts = 0
        while len(to_create) < target and attempts < 3000:
            attempts += 1
            course = random.choice(courses)
            student = random.choice(students)
            pair = (student.id, course.id)

            if pair not in created_pairs:
                created_pairs.add(pair)
                to_create.append(Wishlist(
                    user=student,
                    course=course,
                ))

        Wishlist.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)
        self.stdout.write(f'  → {Wishlist.objects.count()} wishlist dibuat')

    # -------------------------------------------------------------------------
    # Step 10: Seed LessonProgress untuk demo student (mhs001)
    # Agar dashboard terlihat realistis: beberapa course aktif dengan progress bervariasi
    # -------------------------------------------------------------------------
    def _seed_lesson_progress(self, members, contents):
        self.stdout.write('\n[10/10] Membuat lesson progress demo untuk mhs001...')

        if LessonProgress.objects.count() > 0:
            self.stdout.write(f'  → {LessonProgress.objects.count()} lesson progress sudah ada (skip)')
            return

        # Cari mhs001
        try:
            mhs001 = User.objects.get(username='mhs001')
        except User.DoesNotExist:
            self.stdout.write('  → mhs001 tidak ditemukan, skip')
            return

        # Ambil enrollment mhs001
        mhs_memberships = list(
            CourseMember.objects.filter(user_id=mhs001).select_related('course_id')
        )
        if not mhs_memberships:
            self.stdout.write('  → mhs001 tidak memiliki enrollment, skip')
            return

        to_create = []
        created_pairs = set()

        for i, member in enumerate(mhs_memberships):
            course = member.course_id
            course_contents = [c for c in contents if c.course_id_id == course.id]
            if not course_contents:
                continue

            # Variasikan progress: course pertama 100%, sisanya 30-70%
            if i == 0:
                # Course pertama: selesai semua (completed)
                selected = course_contents
            else:
                # Course lainnya: selesai sebagian (30-70%)
                n_complete = max(1, int(len(course_contents) * random.uniform(0.3, 0.7)))
                selected = course_contents[:n_complete]

            for content in selected:
                pair = (member.id, content.id)
                if pair not in created_pairs:
                    created_pairs.add(pair)
                    to_create.append(LessonProgress(
                        member=member,
                        content=content,
                        is_completed=True,
                    ))

        # Tambahkan beberapa progress untuk student lain agar data lebih kaya
        other_members = [m for m in members if m.user_id_id != mhs001.id][:50]
        for member in other_members:
            course = member.course_id
            course_contents = [c for c in contents if c.course_id_id == course.id]
            if not course_contents:
                continue
            # Tandai 1-3 lesson acak sebagai selesai
            n = random.randint(1, min(3, len(course_contents)))
            for content in random.sample(course_contents, n):
                pair = (member.id, content.id)
                if pair not in created_pairs:
                    created_pairs.add(pair)
                    to_create.append(LessonProgress(
                        member=member,
                        content=content,
                        is_completed=True,
                    ))

        if to_create:
            LessonProgress.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)

        self.stdout.write(f'  → {LessonProgress.objects.count()} lesson progress dibuat')

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    def _print_summary(self):
        self.stdout.write('')
        self.stdout.write(self.style.HTTP_INFO('-' * 55))
        self.stdout.write(self.style.HTTP_INFO('  Ringkasan Data'))
        self.stdout.write(self.style.HTTP_INFO('-' * 55))
        self.stdout.write(f'  Group Admin      : {Group.objects.filter(name="Admin").first().user_set.count() if Group.objects.filter(name="Admin").exists() else 0} user')
        self.stdout.write(f'  Group Instructor : {Group.objects.filter(name="Instructor").first().user_set.count() if Group.objects.filter(name="Instructor").exists() else 0} user')
        self.stdout.write(f'  Group Student    : {Group.objects.filter(name="Student").first().user_set.count() if Group.objects.filter(name="Student").exists() else 0} user')
        self.stdout.write(self.style.HTTP_INFO('-' * 55))
        self.stdout.write(
            f"  User pengajar   : {User.objects.filter(username__startswith='dosen').count()}"
        )
        self.stdout.write(
            f"  User mahasiswa  : {User.objects.filter(username__startswith='mhs').count()}"
        )
        self.stdout.write(f'  Category        : {Category.objects.count()}')
        self.stdout.write(f'  Course          : {Course.objects.count()}')
        self.stdout.write(f'  CourseSection   : {CourseSection.objects.count()}')
        self.stdout.write(f'  CourseMember    : {CourseMember.objects.count()}')
        self.stdout.write(f'  CourseContent   : {CourseContent.objects.count()}')
        self.stdout.write(f'  LessonProgress  : {LessonProgress.objects.count()}')
        self.stdout.write(f'  CourseReview    : {CourseReview.objects.count()}')
        self.stdout.write(f'  Wishlist        : {Wishlist.objects.count()}')
        self.stdout.write(f'  Comment         : {Comment.objects.count()}')
        self.stdout.write(self.style.HTTP_INFO('-' * 55))
