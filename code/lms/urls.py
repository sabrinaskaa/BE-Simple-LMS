from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.views.generic import RedirectView

from courses.api import api
from courses.api_v2 import api_v2

# Mount analytics router ke API yang sudah ada
# Semua endpoint analytics muncul di Swagger yang sama (/api/v1/docs)
from analytics.api import analytics_router
api.add_router("/analytics/", analytics_router)

urlpatterns = [
    # Redirect root ke Swagger docs agar tidak 404
    path('', RedirectView.as_view(url='/api/v1/docs', permanent=False)),

    path('admin/', admin.site.urls),
    # path('silk/', include('silk.urls', namespace='silk')),

    # API v1 — semua endpoint utama di bawah /api/v1/
    path("api/v1/", api.urls),

    # API v2 — demonstrasi API versioning paralel tanpa memecah client v1.
    path("api/v2/", api_v2.urls),
    path('', include('courses.urls')),
]

# Sajikan file media saat development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

