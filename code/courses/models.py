from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Q
import os


def lesson_pdf_upload_path(instance, filename):
    """
    Membuat path penyimpanan file PDF materi dengan format:
        {course_id}-{section_id}-{lesson_id}-{timestamp}-{namafile}.pdf

    Contoh: 3-7-42-20260703141523-intro_materi.pdf
    File disimpan di: media/lessons/<path_di_atas>
    """
    from django.utils import timezone as tz

    # Ambil nama file tanpa ekstensi, paksa ekstensi menjadi .pdf
    base_name = os.path.splitext(filename)[0]
    # Ganti karakter tidak aman dengan underscore
    safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in base_name)

    course_id = instance.course_id_id if instance.course_id_id else 0
    section_id = instance.section_id if instance.section_id else 0
    lesson_id = instance.pk if instance.pk else 0
    timestamp = tz.now().strftime("%Y%m%d%H%M%S")

    new_filename = f"{course_id}-{section_id}-{lesson_id}-{timestamp}-{safe_name}.pdf"
    return os.path.join("lessons", new_filename)


class Category(models.Model):
    name = models.CharField("nama kategori", max_length=100, unique=True)
    description = models.TextField("deskripsi", default="-")
    slug = models.SlugField(
        "slug",
        max_length=120,
        unique=True,
        blank=True,
        help_text="Diisi otomatis dari nama kategori jika dikosongkan.",
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Kategori"
        verbose_name_plural = "Kategori"
        ordering = ["name"]


LEVEL_OPTIONS = [
    ('beginner', 'Pemula'),
    ('intermediate', 'Menengah'),
    ('advanced', 'Lanjutan'),
]

STATUS_OPTIONS = [
    ('draft', 'Draft'),
    ('pending_review', 'Menunggu Review'),
    ('published', 'Dipublikasikan'),
    ('archived', 'Diarsipkan'),
]


class Course(models.Model):
    name = models.CharField("nama matkul", max_length=100)
    description = models.TextField("deskripsi", default='-')
    price = models.IntegerField("harga", default=10000)
    image = models.ImageField("gambar", null=True, blank=True)
    level = models.CharField(
        "level",
        max_length=12,
        choices=LEVEL_OPTIONS,
        default='beginner',
    )
    status = models.CharField(
        "status",
        max_length=14,
        choices=STATUS_OPTIONS,
        default='draft',
    )
    rating_avg = models.DecimalField(
        "rata-rata rating",
        max_digits=3,
        decimal_places=2,
        default=0.00,
    )
    total_reviews = models.IntegerField("total review", default=0)
    category = models.ForeignKey(
        Category,
        verbose_name="kategori",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="courses",
    )
    teacher = models.ForeignKey(
        User,
        verbose_name="pengajar",
        on_delete=models.RESTRICT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Mata Kuliah"
        verbose_name_plural = "Mata Kuliah"
        indexes = [
            models.Index(fields=['price'], name='idx_course_price'),
            models.Index(fields=['teacher', 'price'], name='idx_course_teacher_price'),
            models.Index(fields=['status'], name='idx_course_status'),
            models.Index(fields=['level'], name='idx_course_level'),
            models.Index(fields=['rating_avg'], name='idx_course_rating'),
        ]


ROLE_OPTIONS = [
    ('std', "Siswa"),
    ('ast', "Asisten"),
]


class CourseMember(models.Model):
    course_id = models.ForeignKey(
        Course,
        verbose_name="matkul",
        on_delete=models.RESTRICT
    )
    user_id = models.ForeignKey(
        User,
        verbose_name="siswa",
        on_delete=models.RESTRICT
    )
    roles = models.CharField(
        "peran",
        max_length=3,
        choices=ROLE_OPTIONS,
        default='std'
    )

    def __str__(self):
        return f"{self.user_id} - {self.course_id} ({self.roles})"

    class Meta:
        verbose_name = "Anggota Kelas"
        verbose_name_plural = "Anggota Kelas"


class CourseSection(models.Model):
    course = models.ForeignKey(
        Course,
        verbose_name="matkul",
        on_delete=models.CASCADE,
        related_name="sections",
    )
    title = models.CharField("judul section", max_length=200)
    order = models.IntegerField("urutan", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.course.name} — {self.title}"

    class Meta:
        verbose_name = "Section Kelas"
        verbose_name_plural = "Section Kelas"
        ordering = ["course", "order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "order"],
                name="unique_section_order_per_course",
            ),
        ]


class CourseContent(models.Model):
    name = models.CharField("judul konten", max_length=200)
    description = models.TextField("deskripsi singkat", default='-')
    subject = models.CharField("subject/subjudul", max_length=220, blank=True, default="")
    body = models.TextField("isi materi/artikel", blank=True, default="")
    video_url = models.CharField(
        'URL Video',
        max_length=200,
        null=True,
        blank=True
    )
    file_attachment = models.FileField(
        "File PDF Materi",
        null=True,
        blank=True,
        upload_to=lesson_pdf_upload_path,
    )
    course_id = models.ForeignKey(
        Course,
        verbose_name="matkul",
        on_delete=models.RESTRICT
    )
    parent_id = models.ForeignKey(
        "self",
        verbose_name="induk",
        on_delete=models.RESTRICT,
        null=True,
        blank=True
    )
    # Fitur 3: Section & ordering
    section = models.ForeignKey(
        CourseSection,
        verbose_name="section",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contents",
    )
    order = models.IntegerField("urutan dalam section", default=0)
    duration_minutes = models.IntegerField("estimasi durasi (menit)", null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Konten Kelas"
        verbose_name_plural = "Konten Kelas"
        # Urutan: section.order → content.order → id sebagai tiebreaker
        ordering = ["course_id", "section", "order", "id"]
        constraints = [
            # Scope dengan section: (course, section, order) harus unik
            # Catatan: partial index (condition) tidak bisa dikombinasikan dengan deferrable
            models.UniqueConstraint(
                fields=["course_id", "section", "order"],
                condition=Q(section__isnull=False),
                name="unique_content_order_per_course_section",
            ),
            # Scope tanpa section: (course, order) harus unik
            # Catatan: PostgreSQL memperlakukan NULL != NULL di UNIQUE INDEX biasa,
            # sehingga partial index ini diperlukan untuk enforce uniqueness saat section=NULL.
            models.UniqueConstraint(
                fields=["course_id", "order"],
                condition=Q(section__isnull=True),
                name="unique_content_order_per_course_no_section",
            ),
        ]


class Comment(models.Model):
    content_id = models.ForeignKey(
        CourseContent,
        verbose_name="konten",
        on_delete=models.CASCADE
    )
    member_id = models.ForeignKey(
        CourseMember,
        verbose_name="pengguna",
        on_delete=models.CASCADE
    )
    comment = models.TextField('komentar')

    def __str__(self):
        return f"Komentar oleh {self.member_id} pada {self.content_id}"

    class Meta:
        verbose_name = "Komentar"
        verbose_name_plural = "Komentar"


class LessonProgress(models.Model):
    member = models.ForeignKey(
        CourseMember,
        verbose_name="anggota kelas",
        on_delete=models.CASCADE
    )
    content = models.ForeignKey(
        CourseContent,
        verbose_name="konten",
        on_delete=models.CASCADE
    )
    is_completed = models.BooleanField(default=True)
    completed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.member.user_id.username} - {self.content.name}"

    class Meta:
        verbose_name = "Progress Lesson"
        verbose_name_plural = "Progress Lesson"
        unique_together = ("member", "content")


class CourseReview(models.Model):
    course = models.ForeignKey(
        Course,
        verbose_name="matkul",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    user = models.ForeignKey(
        User,
        verbose_name="pengguna",
        on_delete=models.CASCADE,
        related_name="course_reviews",
    )
    rating = models.IntegerField(
        "rating",
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    review = models.TextField("ulasan", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} → {self.course.name} ({self.rating}★)"

    class Meta:
        verbose_name = "Review Course"
        verbose_name_plural = "Review Course"
        unique_together = ("course", "user")


class Wishlist(models.Model):
    user = models.ForeignKey(
        User,
        verbose_name="pengguna",
        on_delete=models.CASCADE,
        related_name="wishlist",
    )
    course = models.ForeignKey(
        Course,
        verbose_name="matkul",
        on_delete=models.CASCADE,
        related_name="wishlisted_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} ♥ {self.course.name}"

    class Meta:
        verbose_name = "Wishlist"
        verbose_name_plural = "Wishlist"
        unique_together = ("user", "course")


PUBLISH_REQUEST_STATUS = [
    ('pending', 'Menunggu'),
    ('approved', 'Disetujui'),
    ('rejected', 'Ditolak'),
]


class CoursePublishRequest(models.Model):
    """Tracks every publish request an instructor submits for admin review."""
    course = models.ForeignKey(
        Course,
        verbose_name="matkul",
        on_delete=models.CASCADE,
        related_name="publish_requests",
    )
    requester = models.ForeignKey(
        User,
        verbose_name="pengaju",
        on_delete=models.CASCADE,
        related_name="publish_requests_sent",
    )
    status = models.CharField(
        "status",
        max_length=10,
        choices=PUBLISH_REQUEST_STATUS,
        default='pending',
    )
    reviewer = models.ForeignKey(
        User,
        verbose_name="reviewer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="publish_requests_reviewed",
    )
    rejection_reason = models.TextField("alasan penolakan", blank=True, default="")
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.course.name} — {self.status} ({self.requester.username})"

    class Meta:
        verbose_name = "Publish Request"
        verbose_name_plural = "Publish Requests"
        ordering = ["-requested_at"]


class CoursePrerequisite(models.Model):
    """A course can require one or more other courses to be completed first."""
    course = models.ForeignKey(
        Course,
        verbose_name="matkul",
        on_delete=models.CASCADE,
        related_name="prerequisites",
    )
    required_course = models.ForeignKey(
        Course,
        verbose_name="matkul prasyarat",
        on_delete=models.CASCADE,
        related_name="required_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.course.name} membutuhkan {self.required_course.name}"

    class Meta:
        verbose_name = "Prasyarat Course"
        verbose_name_plural = "Prasyarat Course"
        unique_together = ("course", "required_course")

class Quiz(models.Model):
    """Kuis yang ditempatkan pada course atau section tertentu."""
    course = models.ForeignKey(
        Course,
        verbose_name="matkul",
        on_delete=models.CASCADE,
        related_name="quizzes",
    )
    section = models.ForeignKey(
        CourseSection,
        verbose_name="section",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quizzes",
    )
    title = models.CharField("judul kuis", max_length=200)
    description = models.TextField("deskripsi", blank=True, default="")
    order = models.IntegerField("urutan", default=1)
    minimum_score = models.IntegerField(
        "nilai minimum",
        default=75,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    question_count = models.IntegerField("jumlah soal per attempt", default=5, validators=[MinValueValidator(1)])
    is_active = models.BooleanField("aktif", default=True)
    created_by = models.ForeignKey(
        User,
        verbose_name="pembuat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_quizzes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.course.name} — {self.title}"

    class Meta:
        verbose_name = "Kuis"
        verbose_name_plural = "Kuis"
        ordering = ["course", "section__order", "order", "id"]
        indexes = [
            models.Index(fields=["course", "section", "order"], name="idx_quiz_course_section"),
            models.Index(fields=["is_active"], name="idx_quiz_is_active"),
        ]


class QuizQuestion(models.Model):
    """Question bank untuk sebuah kuis. Opsi disimpan sebagai list string di JSONField."""
    quiz = models.ForeignKey(
        Quiz,
        verbose_name="kuis",
        on_delete=models.CASCADE,
        related_name="questions",
    )
    question_text = models.TextField("pertanyaan")
    choices = models.JSONField("pilihan jawaban", default=list)
    correct_answer = models.CharField("kunci jawaban", max_length=255)
    explanation = models.TextField("pembahasan", blank=True, default="")
    points = models.IntegerField("poin", default=1, validators=[MinValueValidator(1)])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.question_text[:80]

    class Meta:
        verbose_name = "Bank Soal Kuis"
        verbose_name_plural = "Bank Soal Kuis"
        ordering = ["quiz", "id"]


class QuizAttempt(models.Model):
    quiz = models.ForeignKey(
        Quiz,
        verbose_name="kuis",
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    member = models.ForeignKey(
        CourseMember,
        verbose_name="anggota kelas",
        on_delete=models.CASCADE,
        related_name="quiz_attempts",
    )
    attempt_number = models.IntegerField("nomor attempt", default=1)
    score = models.DecimalField("nilai", max_digits=5, decimal_places=2, default=0)
    passed = models.BooleanField("lulus", default=False)
    cooldown_until = models.DateTimeField("cooldown sampai", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    def mark_submitted(self, score, passed, cooldown_until=None):
        self.score = score
        self.passed = passed
        self.cooldown_until = cooldown_until
        self.submitted_at = timezone.now()
        self.save(update_fields=["score", "passed", "cooldown_until", "submitted_at"])

    def __str__(self):
        return f"{self.member.user_id.username} — {self.quiz.title} ({self.score})"

    class Meta:
        verbose_name = "Attempt Kuis"
        verbose_name_plural = "Attempt Kuis"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["quiz", "member", "created_at"], name="idx_quiz_attempt_member"),
            models.Index(fields=["cooldown_until"], name="idx_quiz_cooldown"),
        ]


class QuizAttemptAnswer(models.Model):
    attempt = models.ForeignKey(
        QuizAttempt,
        verbose_name="attempt",
        on_delete=models.CASCADE,
        related_name="answers",
    )
    question = models.ForeignKey(
        QuizQuestion,
        verbose_name="pertanyaan",
        on_delete=models.CASCADE,
        related_name="attempt_answers",
    )
    selected_answer = models.CharField("jawaban student", max_length=255, blank=True, default="")
    is_correct = models.BooleanField("benar", default=False)

    def __str__(self):
        return f"{self.attempt_id} — {self.question_id}"

    class Meta:
        verbose_name = "Jawaban Attempt Kuis"
        verbose_name_plural = "Jawaban Attempt Kuis"
        unique_together = ("attempt", "question")
