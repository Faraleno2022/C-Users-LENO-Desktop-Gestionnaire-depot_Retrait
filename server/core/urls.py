"""Routage racine."""
from django.contrib import admin
from django.urls import include, path

from sync.views import root as sync_health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/sync/", include("sync.urls")),
    path("api/health/", sync_health),
    path("", include(("web.urls", "web"), namespace="web")),
]
