from django.urls import re_path
from .consumers import ViChatConsumer

websocket_urlpatterns = [
    re_path(r"^ws/vichat/$", ViChatConsumer.as_asgi()),
]
