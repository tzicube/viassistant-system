from django.urls import re_path

from .consumers import ViAssistantConsumer

websocket_urlpatterns = [
    re_path(r"ws/viassistant/$", ViAssistantConsumer.as_asgi()),
]
