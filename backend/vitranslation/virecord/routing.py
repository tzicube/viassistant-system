# vitranslation/virecord/routing.py
from django.urls import path
from .consumers import ViRecordConsumer

websocket_urlpatterns = [
    path("ws/virecord/", ViRecordConsumer.as_asgi()),
]
