"""
URL configuration untuk Simple LMS - Lab 05

Routes:
  /admin/       → Django Admin panel
  /silk/        → Django Silk profiling dashboard
  /             → Semua URL dari app courses (lihat courses/urls.py)
"""

from django.contrib import admin
from django.urls import path, include

from courses.api import api

urlpatterns = [
    path('admin/', admin.site.urls),
    # path('silk/', include('silk.urls', namespace='silk')),
    
    # API baru
    path("api/", api.urls),
    path('', include('courses.urls')),
]
