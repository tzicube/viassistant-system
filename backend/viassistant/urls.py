from django.urls import path
from . import views

urlpatterns = [
    path("api/voice", views.voice),
    path("api/voice/", views.voice),
]
