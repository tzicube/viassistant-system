from django.urls import path 
from .views import api_virecord , api_new_topic , api_record_history , api_record_detail

urlpatterns = [
    path("api/virecord", api_virecord),
    path("api/new_topic", api_new_topic),
    path("api/record_history", api_record_history), 
    path("api/record_detail", api_record_detail),
]
