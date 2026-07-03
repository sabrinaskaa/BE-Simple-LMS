# Generated for upload material wording update.

import courses.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0012_pdf_only_file_attachment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='coursecontent',
            name='file_attachment',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to=courses.models.lesson_pdf_upload_path,
                verbose_name='File Materi',
            ),
        ),
    ]
