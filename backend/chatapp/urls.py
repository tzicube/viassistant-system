from django.urls import path
from .views import chat

urlpatterns = [
    path("api/chat", chat),
]