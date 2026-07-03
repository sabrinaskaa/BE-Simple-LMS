# Generated for richer course content and quiz flow.

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('courses', '0010_pending_review_and_prerequisites'),
    ]

    operations = [
        migrations.AddField(
            model_name='coursecontent',
            name='subject',
            field=models.CharField(blank=True, default='', max_length=220, verbose_name='subject/subjudul'),
        ),
        migrations.AddField(
            model_name='coursecontent',
            name='body',
            field=models.TextField(blank=True, default='', verbose_name='isi materi/artikel'),
        ),
        migrations.AlterField(
            model_name='coursecontent',
            name='description',
            field=models.TextField(default='-', verbose_name='deskripsi singkat'),
        ),
        migrations.CreateModel(
            name='Quiz',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200, verbose_name='judul kuis')),
                ('description', models.TextField(blank=True, default='', verbose_name='deskripsi')),
                ('order', models.IntegerField(default=1, verbose_name='urutan')),
                ('minimum_score', models.IntegerField(default=75, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)], verbose_name='nilai minimum')),
                ('question_count', models.IntegerField(default=5, validators=[django.core.validators.MinValueValidator(1)], verbose_name='jumlah soal per attempt')),
                ('is_active', models.BooleanField(default=True, verbose_name='aktif')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='quizzes', to='courses.course', verbose_name='matkul')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_quizzes', to=settings.AUTH_USER_MODEL, verbose_name='pembuat')),
                ('section', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='quizzes', to='courses.coursesection', verbose_name='section')),
            ],
            options={
                'verbose_name': 'Kuis',
                'verbose_name_plural': 'Kuis',
                'ordering': ['course', 'section__order', 'order', 'id'],
            },
        ),
        migrations.CreateModel(
            name='QuizQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question_text', models.TextField(verbose_name='pertanyaan')),
                ('choices', models.JSONField(default=list, verbose_name='pilihan jawaban')),
                ('correct_answer', models.CharField(max_length=255, verbose_name='kunci jawaban')),
                ('explanation', models.TextField(blank=True, default='', verbose_name='pembahasan')),
                ('points', models.IntegerField(default=1, validators=[django.core.validators.MinValueValidator(1)], verbose_name='poin')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('quiz', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='questions', to='courses.quiz', verbose_name='kuis')),
            ],
            options={
                'verbose_name': 'Bank Soal Kuis',
                'verbose_name_plural': 'Bank Soal Kuis',
                'ordering': ['quiz', 'id'],
            },
        ),
        migrations.CreateModel(
            name='QuizAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('attempt_number', models.IntegerField(default=1, verbose_name='nomor attempt')),
                ('score', models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name='nilai')),
                ('passed', models.BooleanField(default=False, verbose_name='lulus')),
                ('cooldown_until', models.DateTimeField(blank=True, null=True, verbose_name='cooldown sampai')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='quiz_attempts', to='courses.coursemember', verbose_name='anggota kelas')),
                ('quiz', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attempts', to='courses.quiz', verbose_name='kuis')),
            ],
            options={
                'verbose_name': 'Attempt Kuis',
                'verbose_name_plural': 'Attempt Kuis',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='QuizAttemptAnswer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('selected_answer', models.CharField(blank=True, default='', max_length=255, verbose_name='jawaban student')),
                ('is_correct', models.BooleanField(default=False, verbose_name='benar')),
                ('attempt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='courses.quizattempt', verbose_name='attempt')),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attempt_answers', to='courses.quizquestion', verbose_name='pertanyaan')),
            ],
            options={
                'verbose_name': 'Jawaban Attempt Kuis',
                'verbose_name_plural': 'Jawaban Attempt Kuis',
                'unique_together': {('attempt', 'question')},
            },
        ),
        migrations.AddIndex(
            model_name='quiz',
            index=models.Index(fields=['course', 'section', 'order'], name='idx_quiz_course_section'),
        ),
        migrations.AddIndex(
            model_name='quiz',
            index=models.Index(fields=['is_active'], name='idx_quiz_is_active'),
        ),
        migrations.AddIndex(
            model_name='quizattempt',
            index=models.Index(fields=['quiz', 'member', 'created_at'], name='idx_quiz_attempt_member'),
        ),
        migrations.AddIndex(
            model_name='quizattempt',
            index=models.Index(fields=['cooldown_until'], name='idx_quiz_cooldown'),
        ),
    ]
