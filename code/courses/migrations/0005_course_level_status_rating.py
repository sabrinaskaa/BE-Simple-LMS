from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0004_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='level',
            field=models.CharField(
                choices=[('beginner', 'Pemula'), ('intermediate', 'Menengah'), ('advanced', 'Lanjutan')],
                default='beginner',
                max_length=12,
                verbose_name='level',
            ),
        ),
        migrations.AddField(
            model_name='course',
            name='status',
            field=models.CharField(
                choices=[('draft', 'Draft'), ('published', 'Dipublikasikan'), ('archived', 'Diarsipkan')],
                default='published',
                max_length=10,
                verbose_name='status',
            ),
        ),
        migrations.AddField(
            model_name='course',
            name='rating_avg',
            field=models.DecimalField(
                decimal_places=2,
                default=0.0,
                max_digits=3,
                verbose_name='rata-rata rating',
            ),
        ),
        migrations.AddField(
            model_name='course',
            name='total_reviews',
            field=models.IntegerField(default=0, verbose_name='total review'),
        ),
        migrations.AddIndex(
            model_name='course',
            index=models.Index(fields=['status'], name='idx_course_status'),
        ),
        migrations.AddIndex(
            model_name='course',
            index=models.Index(fields=['level'], name='idx_course_level'),
        ),
        migrations.AddIndex(
            model_name='course',
            index=models.Index(fields=['rating_avg'], name='idx_course_rating'),
        ),
    ]
