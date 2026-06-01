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
