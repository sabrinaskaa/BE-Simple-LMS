import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0006_coursesection_content_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Buat model CourseReview
        migrations.CreateModel(
            name='CourseReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rating', models.IntegerField(
                    validators=[
                        django.core.validators.MinValueValidator(1),
                        django.core.validators.MaxValueValidator(5),
                    ],
                    verbose_name='rating',
                )),
                ('review', models.TextField(blank=True, default='', verbose_name='ulasan')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('course', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='reviews',
                    to='courses.course',
                    verbose_name='matkul',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='course_reviews',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='pengguna',
                )),
            ],
            options={
                'verbose_name': 'Review Course',
                'verbose_name_plural': 'Review Course',
                'unique_together': {('course', 'user')},
            },
        ),
        # 2. Buat model Wishlist
        migrations.CreateModel(
            name='Wishlist',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('course', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='wishlisted_by',
                    to='courses.course',
                    verbose_name='matkul',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='wishlist',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='pengguna',
                )),
            ],
            options={
                'verbose_name': 'Wishlist',
                'verbose_name_plural': 'Wishlist',
                'unique_together': {('user', 'course')},
            },
        ),
    ]
