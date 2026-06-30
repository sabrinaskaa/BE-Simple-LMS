from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('courses', '0009_ordering_constraints'),
    ]

    operations = [
        # 1. Update Course.status field: perluas max_length & tambah pilihan pending_review
        migrations.AlterField(
            model_name='course',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', 'Draft'),
                    ('pending_review', 'Menunggu Review'),
                    ('published', 'Dipublikasikan'),
                    ('archived', 'Diarsipkan'),
                ],
                default='draft',
                max_length=14,
                verbose_name='status',
            ),
        ),

        # 2. Buat tabel CoursePublishRequest
        migrations.CreateModel(
            name='CoursePublishRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Menunggu'),
                        ('approved', 'Disetujui'),
                        ('rejected', 'Ditolak'),
                    ],
                    default='pending',
                    max_length=10,
                    verbose_name='status',
                )),
                ('rejection_reason', models.TextField(blank=True, default='', verbose_name='alasan penolakan')),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('course', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='publish_requests',
                    to='courses.course',
                    verbose_name='matkul',
                )),
                ('requester', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='publish_requests_sent',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='pengaju',
                )),
                ('reviewer', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='publish_requests_reviewed',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='reviewer',
                )),
            ],
            options={
                'verbose_name': 'Publish Request',
                'verbose_name_plural': 'Publish Requests',
                'ordering': ['-requested_at'],
            },
        ),

        # 3. Buat tabel CoursePrerequisite
        migrations.CreateModel(
            name='CoursePrerequisite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('course', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='prerequisites',
                    to='courses.course',
                    verbose_name='matkul',
                )),
                ('required_course', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='required_by',
                    to='courses.course',
                    verbose_name='matkul prasyarat',
                )),
            ],
            options={
                'verbose_name': 'Prasyarat Course',
                'verbose_name_plural': 'Prasyarat Course',
            },
        ),

        # 4. Tambahkan unique constraint untuk CoursePrerequisite
        migrations.AlterUniqueTogether(
            name='courseprerequisite',
            unique_together={('course', 'required_course')},
        ),
    ]
