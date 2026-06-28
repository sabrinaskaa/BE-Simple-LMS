import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0005_course_level_status_rating'),
    ]

    operations = [
        # 1. Buat model CourseSection
        migrations.CreateModel(
            name='CourseSection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200, verbose_name='judul section')),
                ('order', models.IntegerField(default=0, verbose_name='urutan')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('course', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='sections',
                    to='courses.course',
                    verbose_name='matkul',
                )),
            ],
            options={
                'verbose_name': 'Section Kelas',
                'verbose_name_plural': 'Section Kelas',
                'ordering': ['course', 'order'],
            },
        ),
        # 2. Tambah field section (FK nullable) ke CourseContent
        migrations.AddField(
            model_name='coursecontent',
            name='section',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='contents',
                to='courses.coursesection',
                verbose_name='section',
            ),
        ),
        # 3. Tambah field order ke CourseContent
        migrations.AddField(
            model_name='coursecontent',
            name='order',
            field=models.IntegerField(default=0, verbose_name='urutan dalam section'),
        ),
        # 4. Tambah field duration_minutes ke CourseContent
        migrations.AddField(
            model_name='coursecontent',
            name='duration_minutes',
            field=models.IntegerField(blank=True, null=True, verbose_name='estimasi durasi (menit)'),
        ),
    ]
