from django.db import migrations, models
import django.db.models


def fix_duplicate_orders(apps, schema_editor):
    CourseSection = apps.get_model('courses', 'CourseSection')
    CourseContent = apps.get_model('courses', 'CourseContent')

    # Fix duplikat di CourseSection
    from django.db.models import Count

    # Temukan (course_id, order) yang duplikat
    dup_sections = (
        CourseSection.objects
        .values('course_id', 'order')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
    )

    for dup in dup_sections:
        sections = list(
            CourseSection.objects
            .filter(course_id=dup['course_id'], order=dup['order'])
            .order_by('id')
        )
        # Pertahankan yang pertama, geser sisanya
        for idx, section in enumerate(sections[1:], start=1):
            # Pakai offset besar dahulu untuk menghindari conflict sementara
            section.order = section.order + 100000 + idx
            section.save()

    # Re-number semua section per course agar bersih dan sequential
    from collections import defaultdict
    sections_by_course = defaultdict(list)
    for s in CourseSection.objects.order_by('course_id', 'order', 'id'):
        sections_by_course[s.course_id].append(s)

    for course_id, sections in sections_by_course.items():
        for new_order, section in enumerate(sections, start=1):
            if section.order != new_order:
                section.order = new_order
                section.save()

    # ── Fix duplikat di CourseContent ────────────────────────────────────────

    # Scope 1: content dengan section (course_id, section_id, order)
    dup_contents_with_section = (
        CourseContent.objects
        .filter(section__isnull=False)
        .values('course_id', 'section_id', 'order')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
    )

    for dup in dup_contents_with_section:
        contents = list(
            CourseContent.objects
            .filter(
                course_id=dup['course_id'],
                section_id=dup['section_id'],
                order=dup['order'],
            )
            .order_by('id')
        )
        for idx, content in enumerate(contents[1:], start=1):
            content.order = content.order + 100000 + idx
            content.save()

    # Scope 2: content tanpa section (course_id, section=None, order)
    dup_contents_no_section = (
        CourseContent.objects
        .filter(section__isnull=True)
        .values('course_id', 'order')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
    )

    for dup in dup_contents_no_section:
        contents = list(
            CourseContent.objects
            .filter(
                course_id=dup['course_id'],
                section__isnull=True,
                order=dup['order'],
            )
            .order_by('id')
        )
        for idx, content in enumerate(contents[1:], start=1):
            content.order = content.order + 100000 + idx
            content.save()

    # Re-number content per (course, section) scope
    # Scope dengan section
    from itertools import groupby
    contents_with_section = list(
        CourseContent.objects
        .filter(section__isnull=False)
        .order_by('course_id', 'section_id', 'order', 'id')
    )
    for key, group in groupby(contents_with_section, key=lambda c: (c.course_id, c.section_id)):
        for new_order, content in enumerate(group, start=1):
            if content.order != new_order:
                content.order = new_order
                content.save()

    # Scope tanpa section
    contents_no_section = list(
        CourseContent.objects
        .filter(section__isnull=True)
        .order_by('course_id', 'order', 'id')
    )
    for key, group in groupby(contents_no_section, key=lambda c: c.course_id):
        for new_order, content in enumerate(group, start=1):
            if content.order != new_order:
                content.order = new_order
                content.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    # atomic=False diperlukan agar RunPython (UPDATE rows dengan deferred FK)
    # dan AddConstraint (CREATE INDEX) tidak berada dalam satu transaksi.
    # PostgreSQL akan error "pending trigger events" jika keduanya dalam 1 transaksi.
    atomic = False

    dependencies = [
        ('courses', '0008_alter_coursecontent_options'),
    ]

    operations = [
        # Step 1: Bersihkan duplikat sebelum constraint ditambah
        migrations.RunPython(fix_duplicate_orders, reverse_code=noop),

        # Step 2: Update Meta ordering CourseSection
        migrations.AlterModelOptions(
            name='coursesection',
            options={
                'ordering': ['course', 'order', 'id'],
                'verbose_name': 'Section Kelas',
                'verbose_name_plural': 'Section Kelas',
            },
        ),

        # Step 3: Update Meta ordering CourseContent
        migrations.AlterModelOptions(
            name='coursecontent',
            options={
                'ordering': ['course_id', 'section', 'order', 'id'],
                'verbose_name': 'Konten Kelas',
                'verbose_name_plural': 'Konten Kelas',
            },
        ),

        # Step 4: Tambah UniqueConstraint CourseSection(course, order)
        migrations.AddConstraint(
            model_name='coursesection',
            constraint=models.UniqueConstraint(
                fields=['course', 'order'],
                name='unique_section_order_per_course',
            ),
        ),

        # Step 5: Tambah partial UniqueConstraint CourseContent — dengan section
        # Catatan: partial index (condition) tidak bisa dikombinasikan dengan deferrable
        migrations.AddConstraint(
            model_name='coursecontent',
            constraint=models.UniqueConstraint(
                fields=['course_id', 'section', 'order'],
                condition=models.Q(section__isnull=False),
                name='unique_content_order_per_course_section',
            ),
        ),

        # Step 6: Tambah partial UniqueConstraint CourseContent — tanpa section
        # Catatan: partial index (condition) tidak bisa dikombinasikan dengan deferrable
        migrations.AddConstraint(
            model_name='coursecontent',
            constraint=models.UniqueConstraint(
                fields=['course_id', 'order'],
                condition=models.Q(section__isnull=True),
                name='unique_content_order_per_course_no_section',
            ),
        ),
    ]
