"""
Views untuk Simple LMS - Lab 05: Optimasi Database

File ini dibagi menjadi 3 bagian:

  BAGIAN 1 - Views dengan N+1 Problem
    Gunakan Django Silk (http://localhost:8000/silk/) untuk mengamati
    jumlah query yang dihasilkan oleh setiap endpoint.

  BAGIAN 2 - Views Teroptimasi (Referensi Solusi)
    Bandingkan jumlah query di Silk setelah mengakses endpoint ini.

  BAGIAN 3 - Statistik
    Contoh penggunaan aggregate() untuk kalkulasi di level database.

Petunjuk Lab:
  1. Jalankan python manage.py seed_data untuk mengisi data
  2. Akses endpoint BAGIAN 1, amati jumlah query di Silk
  3. Coba optimalkan sendiri sebelum melihat BAGIAN 2
  4. Bandingkan hasilnya
"""

from django.db.models import Avg, Count, Max, Min, Prefetch, F
from django.http import JsonResponse

from .models import Comment, Course, CourseContent, CourseMember

def course_list_baseline(request):
    courses = Course.objects.all()
    data = []

    for c in courses:
        data.append({
            'course': c.name,
            'teacher': c.teacher.username,
        })

    return JsonResponse({'data': data})


def course_list_optimized(request):
    courses = Course.objects.select_related('teacher').all()
    data = []

    for c in courses:
        data.append({
            'course': c.name,
            'teacher': c.teacher.username,
        })

    return JsonResponse({'data': data})


def course_members_baseline(request):
    courses = Course.objects.all()
    payload = []

    for c in courses:
        payload.append({
            'course': c.name,
            'member_count': c.coursemember_set.count(),
        })

    return JsonResponse({'data': payload})


def course_members_optimized(request):
    courses = Course.objects.prefetch_related('coursemember_set').all()
    payload = []

    for c in courses:
        payload.append({
            'course': c.name,
            'member_count': c.coursemember_set.count(),
        })

    return JsonResponse({'data': payload})

def course_dashboard_baseline(request):
    courses = Course.objects.all()

    course_data = []
    total_courses = 0
    prices = []

    for c in courses:
        member_count = CourseMember.objects.filter(course_id=c).count()

        course_data.append({
            'course': c.name,
            'member_count': member_count,
            'price': float(c.price),
        })

        total_courses += 1
        prices.append(float(c.price))

    stats = {
        'total': total_courses,
        'max_price': max(prices) if prices else 0,
        'min_price': min(prices) if prices else 0,
        'avg_price': sum(prices) / len(prices) if prices else 0,
    }

    return JsonResponse({
        'stats': stats,
        'courses': course_data,
    })

def course_dashboard_optimized(request):
    courses = Course.objects.annotate(
        member_count=Count('coursemember')
    ).order_by('-member_count')

    stats = Course.objects.aggregate(
        total=Count('id'),
        max_price=Max('price'),
        min_price=Min('price'),
        avg_price=Avg('price'),
    )

    course_data = []
    for c in courses:
        course_data.append({
            'course': c.name,
            'member_count': c.member_count,
            'price': float(c.price),
        })

    return JsonResponse({
        'stats': stats,
        'courses': course_data,
    })

def bulk_insert_baseline(request):
    course = Course.objects.first()

    if not course:
        return JsonResponse({'error': 'No course found'}, status=404)

    for i in range(1000):
        content = CourseContent(
            name=f'Content {i}',
            course_id=course
        )
        content.save()

    return JsonResponse({'message': 'Baseline bulk insert selesai'})

def bulk_insert_optimized(request):
    course = Course.objects.first()

    if not course:
        return JsonResponse({'error': 'No course found'}, status=404)

    contents = [
        CourseContent(name=f'Content {i}', course_id=course)
        for i in range(1000)
    ]

    CourseContent.objects.bulk_create(contents, batch_size=500)

    return JsonResponse({'message': 'Optimized bulk insert selesai'})

def bulk_update_baseline(request):
    courses = Course.objects.all()

    for c in courses:
        c.price = c.price * 1.1
        c.save()

    return JsonResponse({'message': 'Baseline bulk update selesai'})

def bulk_update_optimized(request):
    Course.objects.all().update(price=F('price') * 1.1)

    return JsonResponse({'message': 'Optimized bulk update selesai'})