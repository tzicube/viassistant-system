from django.urls import path

from . import views

urlpatterns = [
    path("viassistant/voice", views.voice, name="viassistant_voice"),
]
