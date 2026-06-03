from django.urls import path

from sync import views

urlpatterns = [
    path("ping/", views.ping, name="sync-ping"),
    path("push/", views.push, name="sync-push"),
    path("pull/", views.pull, name="sync-pull"),
]
