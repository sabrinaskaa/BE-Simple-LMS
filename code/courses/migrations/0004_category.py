import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0003_lessonprogress'),
    ]

    operations = [
        # 1. Buat tabel Category terlebih dahulu
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='nama kategori')),
                ('description', models.TextField(default='-', verbose_name='deskripsi')),
                ('slug', models.SlugField(
                    blank=True,
                    help_text='Diisi otomatis dari nama kategori jika dikosongkan.',
                    max_length=120,
                    unique=True,
                    verbose_name='slug',
                )),
            ],
            options={
                'verbose_name': 'Kategori',
                'verbose_name_plural': 'Kategori',
                'ordering': ['name'],
            },
        ),
        # 2. Tambah kolom category_id (nullable FK) ke tabel Course
        migrations.AddField(
            model_name='course',
            name='category',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='courses',
                to='courses.category',
                verbose_name='kategori',
            ),
        ),
    ]
