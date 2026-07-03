import random

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Avg, Count

from courses.models import (
    Category,
    Comment,
    Course,
    CourseContent,
    CourseMember,
    CourseReview,
    CourseSection,
    LessonProgress,
    Quiz,
    QuizQuestion,
    Wishlist,
)

FIRST_NAMES = ['Budi', 'Siti', 'Ahmad', 'Dewi', 'Reza', 'Putri', 'Andi', 'Rina', 'Hendra', 'Yuli']
LAST_NAMES = ['Santoso', 'Wijaya', 'Kusuma', 'Rahayu', 'Pratama', 'Sari', 'Hidayat', 'Permata', 'Nugroho', 'Lestari']
LEVELS = ['beginner', 'intermediate', 'advanced']
PRICES = [50000, 75000, 100000, 125000, 150000, 200000]

COURSE_DATA = [
    ('Pemrograman Web Modern', 'Pemrograman', 'Belajar HTML, CSS, JavaScript, React, dan REST API dari dasar.'),
    ('Backend Python dengan Django', 'Pemrograman', 'Membangun backend API, autentikasi JWT, dan integrasi database.'),
    ('Basis Data Relasional', 'Basis Data', 'Desain database, normalisasi, SQL, dan optimasi query.'),
    ('Dasar Keamanan Siber', 'Jaringan & Keamanan', 'Konsep keamanan aplikasi, autentikasi, hashing, dan proteksi data.'),
    ('Machine Learning untuk Pemula', 'Data Science', 'Pipeline data, model supervised learning, evaluasi, dan deployment sederhana.'),
    ('DevOps dengan Docker', 'DevOps & Cloud', 'Container, docker compose, environment variable, dan deployment aplikasi.'),
]

SECTION_TITLES = ['Pendahuluan', 'Materi Inti', 'Praktik Terarah', 'Evaluasi']
YOUTUBE_LINKS = [
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    'https://www.youtube.com/watch?v=ysz5S6PUM-U',
    'https://www.youtube.com/watch?v=jNQXAC9IVRw',
]

QUIZ_TEMPLATES = [
    ('Apa tujuan utama materi pada section ini?', ['Memahami konsep inti', 'Menghapus database', 'Menurunkan keamanan', 'Mengabaikan dokumentasi'], 'Memahami konsep inti'),
    ('Apa kebiasaan belajar yang paling tepat sebelum kuis?', ['Membaca ulang materi', 'Menebak semua jawaban', 'Melewati semua lesson', 'Menghapus akun'], 'Membaca ulang materi'),
    ('Nilai minimum kelulusan kuis pada sistem ini adalah?', ['75', '50', '25', '1000'], '75'),
    ('Apa fungsi question bank?', ['Menyediakan kumpulan soal', 'Menghapus course', 'Mengganti instructor', 'Membuka semua section otomatis'], 'Menyediakan kumpulan soal'),
    ('Mengapa urutan lesson penting?', ['Agar pembelajaran bertahap', 'Agar siswa melewati materi', 'Agar kuis tidak perlu dikerjakan', 'Agar file tidak bisa diupload'], 'Agar pembelajaran bertahap'),
]


class Command(BaseCommand):
    help = 'Seed database Simple LMS dengan course, section, artikel lesson, quiz, dan question bank.'

    def add_arguments(self, parser):
        parser.add_argument('--teachers', type=int, default=20, help='Jumlah instructor minimal untuk seed besar')
        parser.add_argument('--students', type=int, default=200, help='Jumlah student untuk membuat enrollment')
        parser.add_argument('--courses', type=int, default=100, help='Jumlah course minimal untuk optimasi database')
        parser.add_argument('--members', type=int, default=500, help='Jumlah enrollment/course member minimal')
        parser.add_argument('--comments', type=int, default=1000, help='Jumlah komentar lesson minimal')

    def handle(self, *args, **options):
        random.seed(42)
        self.stdout.write(self.style.HTTP_INFO('=' * 60))
        self.stdout.write(self.style.HTTP_INFO('  Seeding Data - Simple LMS Rich Course Flow'))
        self.stdout.write(self.style.HTTP_INFO('=' * 60))

        with transaction.atomic():
            groups = self._seed_groups()
            teachers = self._seed_teachers(groups['instructor'], options['teachers'])
            students = self._seed_students(groups['student'], options['students'])
            categories = self._seed_categories()
            courses = self._seed_courses(teachers, categories, options['courses'])
            self._seed_curriculum(courses)
            members = self._seed_members(courses, students, options['members'])
            self._seed_reviews(courses, members)
            self._seed_wishlist(courses, students)
            self._seed_comments(courses, members, options['comments'])
            self._seed_progress_demo(courses, students)

        self._print_summary()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Seeding selesai!'))
        self.stdout.write('  Admin     : admin / admin123')
        self.stdout.write(f'  Instructor: dosen01 - dosen{options["teachers"]:02d} / password123')
        self.stdout.write(f'  Student   : mhs001 - mhs{options["students"]:03d} / password123')

    def _seed_groups(self):
        self.stdout.write('\n[1/10] Menyiapkan role...')
        admin_group, _ = Group.objects.get_or_create(name='Admin')
        instructor_group, _ = Group.objects.get_or_create(name='Instructor')
        student_group, _ = Group.objects.get_or_create(name='Student')
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@lms.ac.id',
                'first_name': 'Super',
                'last_name': 'Admin',
                'is_staff': True,
                'is_superuser': True,
                'password': make_password('admin123'),
            },
        )
        if created:
            admin_user.groups.add(admin_group)
        return {'admin': admin_group, 'instructor': instructor_group, 'student': student_group}

    def _seed_teachers(self, instructor_group, target_count=20):
        self.stdout.write('[2/10] Menyiapkan instructor...')
        teachers = []
        for i in range(1, target_count + 1):
            username = f'dosen{i:02d}'
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': f'{username}@univ.ac.id',
                    'first_name': FIRST_NAMES[(i - 1) % len(FIRST_NAMES)],
                    'last_name': LAST_NAMES[(i - 1) % len(LAST_NAMES)],
                    'password': make_password('password123'),
                },
            )
            user.groups.add(instructor_group)
            teachers.append(user)
        return teachers

    def _seed_students(self, student_group, target_count=200):
        self.stdout.write('[3/10] Menyiapkan student...')
        students = []
        for i in range(1, target_count + 1):
            username = f'mhs{i:03d}'
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': f'{username}@student.univ.ac.id',
                    'first_name': random.choice(FIRST_NAMES),
                    'last_name': random.choice(LAST_NAMES),
                    'password': make_password('password123'),
                },
            )
            user.groups.add(student_group)
            students.append(user)
        return students

    def _seed_categories(self):
        self.stdout.write('[4/10] Menyiapkan kategori...')
        rows = [
            ('Pemrograman', 'Kursus pengembangan aplikasi dan bahasa pemrograman.'),
            ('Basis Data', 'Kursus desain dan manajemen database.'),
            ('Jaringan & Keamanan', 'Kursus jaringan komputer dan keamanan siber.'),
            ('Data Science', 'Kursus analisis data, AI, dan machine learning.'),
            ('DevOps & Cloud', 'Kursus deployment, container, dan cloud computing.'),
        ]
        categories = {}
        for name, desc in rows:
            cat, _ = Category.objects.get_or_create(name=name, defaults={'description': desc})
            categories[name] = cat
        return categories

    def _seed_courses(self, teachers, categories, target_count=100):
        self.stdout.write('[5/10] Menyiapkan course published...')
        courses = []
        category_names = list(categories.keys())
        for idx in range(target_count):
            base_name, category_name, description = COURSE_DATA[idx % len(COURSE_DATA)]
            name = base_name if idx < len(COURSE_DATA) else f'{base_name} #{idx + 1:03d}'
            category_name = category_name if category_name in categories else category_names[idx % len(category_names)]
            course, created = Course.objects.get_or_create(
                name=name,
                defaults={
                    'description': description,
                    'price': PRICES[idx % len(PRICES)],
                    'teacher': teachers[idx % len(teachers)],
                    'category': categories.get(category_name),
                    'level': LEVELS[idx % len(LEVELS)],
                    'status': 'published',
                },
            )
            if not created:
                course.description = description
                course.teacher = teachers[idx % len(teachers)]
                course.category = categories.get(category_name)
                course.status = 'published'
                course.save(update_fields=['description', 'teacher', 'category', 'status'])
            courses.append(course)
        return courses

    def _seed_curriculum(self, courses):
        self.stdout.write('[6/10] Menyiapkan section, artikel lesson, quiz, dan question bank...')
        for course in courses:
            for s_idx, section_title in enumerate(SECTION_TITLES, start=1):
                section, _ = CourseSection.objects.get_or_create(
                    course=course,
                    order=s_idx,
                    defaults={'title': section_title},
                )
                if section.title != section_title:
                    section.title = section_title
                    section.save(update_fields=['title'])

                for l_idx in range(1, 3):
                    title = f'{section_title}: Materi {l_idx}'
                    subject = f'{course.name} — {section_title}'
                    body = (
                        f'Materi ini membahas {section_title.lower()} pada course {course.name}.\n\n'
                        'Baca bagian ini seperti artikel pembelajaran. Instructor dapat menulis penjelasan panjang, '
                        'menyisipkan video, dan menambahkan file pendukung. Student wajib menyelesaikan lesson secara berurutan '
                        'sebelum membuka section atau kuis berikutnya.\n\n'
                        'Poin penting:\n'
                        '- Pahami konsep utama terlebih dahulu.\n'
                        '- Catat istilah yang belum dipahami.\n'
                        '- Ulangi materi sebelum mengerjakan kuis.'
                    )
                    content, created = CourseContent.objects.get_or_create(
                        course_id=course,
                        section=section,
                        order=l_idx,
                        defaults={
                            'name': title,
                            'description': f'Ringkasan {title}',
                            'subject': subject,
                            'body': body,
                            'video_url': YOUTUBE_LINKS[(s_idx + l_idx) % len(YOUTUBE_LINKS)] if l_idx == 1 else '',
                            'duration_minutes': random.choice([10, 15, 20, 30]),
                        },
                    )
                    if not created:
                        content.subject = subject
                        content.body = body
                        content.description = f'Ringkasan {title}'
                        content.save(update_fields=['subject', 'body', 'description'])

                quiz, created = Quiz.objects.get_or_create(
                    course=course,
                    section=section,
                    order=1,
                    defaults={
                        'title': f'Kuis {section_title}',
                        'description': f'Evaluasi singkat untuk section {section_title}. Nilai minimum 75.',
                        'minimum_score': 75,
                        'question_count': 3,
                        'is_active': True,
                        'created_by': course.teacher,
                    },
                )
                if not created:
                    quiz.title = f'Kuis {section_title}'
                    quiz.minimum_score = 75
                    quiz.question_count = 3
                    quiz.is_active = True
                    quiz.save(update_fields=['title', 'minimum_score', 'question_count', 'is_active'])

                if quiz.questions.count() < len(QUIZ_TEMPLATES):
                    existing_texts = set(quiz.questions.values_list('question_text', flat=True))
                    for question_text, choices, correct in QUIZ_TEMPLATES:
                        final_text = f'{question_text} ({section_title})'
                        if final_text in existing_texts:
                            continue
                        QuizQuestion.objects.create(
                            quiz=quiz,
                            question_text=final_text,
                            choices=choices,
                            correct_answer=correct,
                            explanation='Pembahasan tersedia setelah evaluasi dari instructor.',
                            points=1,
                        )

    def _seed_members(self, courses, students, target_count=500):
        self.stdout.write('[7/10] Menyiapkan enrollment...')
        members = list(CourseMember.objects.select_related('course_id', 'user_id').all()[:target_count])
        seen = {(m.course_id_id, m.user_id_id) for m in members}
        attempts = 0
        while len(members) < target_count and attempts < target_count * 20:
            attempts += 1
            student = random.choice(students)
            course = random.choice(courses)
            key = (course.id, student.id)
            if key in seen:
                continue
            member, _ = CourseMember.objects.get_or_create(course_id=course, user_id=student, defaults={'roles': 'std'})
            members.append(member)
            seen.add(key)
        return members

    def _seed_reviews(self, courses, members):
        self.stdout.write('[8/10] Menyiapkan review...')
        review_texts = [
            'Materinya runtut dan enak dibaca.',
            'Struktur course mirip platform e-learning modern.',
            'Kuis membantu mengecek pemahaman.',
            'Butuh lebih banyak contoh, tapi sudah bagus.',
        ]
        for member in members[:60]:
            CourseReview.objects.get_or_create(
                course=member.course_id,
                user=member.user_id,
                defaults={'rating': random.choice([4, 4, 5, 5, 3]), 'review': random.choice(review_texts)},
            )
        agg = CourseReview.objects.values('course_id').annotate(avg=Avg('rating'), total=Count('id'))
        agg_map = {item['course_id']: item for item in agg}
        for course in courses:
            data = agg_map.get(course.id)
            course.rating_avg = round(data['avg'] or 0, 2) if data else 0
            course.total_reviews = data['total'] if data else 0
            course.save(update_fields=['rating_avg', 'total_reviews'])

    def _seed_wishlist(self, courses, students):
        self.stdout.write('[9/10] Menyiapkan wishlist...')
        for student in students[:12]:
            for course in random.sample(courses, k=min(2, len(courses))):
                Wishlist.objects.get_or_create(user=student, course=course)

    def _seed_comments(self, courses, members, target_count=1000):
        self.stdout.write('[10/10] Menyiapkan komentar lesson...')
        comments = ['Materinya jelas.', 'Saya akan ulangi sebelum kuis.', 'Contohnya membantu.', 'Bagian ini penting untuk dipahami.']
        existing = Comment.objects.count()
        if existing >= target_count:
            return
        lessons_by_course = {
            course.id: list(CourseContent.objects.filter(course_id=course))
            for course in courses
        }
        batch = []
        for i in range(target_count - existing):
            member = random.choice(members)
            lessons = lessons_by_course.get(member.course_id_id) or []
            if not lessons:
                continue
            batch.append(Comment(
                content_id=random.choice(lessons),
                member_id=member,
                comment=f'{random.choice(comments)} #{existing + i + 1}',
            ))
            if len(batch) >= 500:
                Comment.objects.bulk_create(batch, batch_size=500)
                batch = []
        if batch:
            Comment.objects.bulk_create(batch, batch_size=500)

    def _seed_progress_demo(self, courses, students):
        demo_student = students[0] if students else None
        if not demo_student:
            return
        course = courses[0]
        member, _ = CourseMember.objects.get_or_create(course_id=course, user_id=demo_student, defaults={'roles': 'std'})
        first_section = CourseSection.objects.filter(course=course).order_by('order').first()
        if first_section:
            for lesson in CourseContent.objects.filter(course_id=course, section=first_section).order_by('order'):
                LessonProgress.objects.get_or_create(member=member, content=lesson, defaults={'is_completed': True})

    def _print_summary(self):
        self.stdout.write('')
        self.stdout.write(self.style.HTTP_INFO('-' * 60))
        self.stdout.write(f'  Categories     : {Category.objects.count()}')
        self.stdout.write(f'  Courses        : {Course.objects.count()}')
        self.stdout.write(f'  Sections       : {CourseSection.objects.count()}')
        self.stdout.write(f'  Lessons        : {CourseContent.objects.count()}')
        self.stdout.write(f'  Quizzes        : {Quiz.objects.count()}')
        self.stdout.write(f'  Questions      : {QuizQuestion.objects.count()}')
        self.stdout.write(f'  Enrollments    : {CourseMember.objects.count()}')
        self.stdout.write(self.style.HTTP_INFO('-' * 60))
