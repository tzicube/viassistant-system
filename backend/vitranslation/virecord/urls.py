from django.urls import path
from . import views

urlpatterns = [
    # NEW TOPIC
    path("api/new_topic", views.api_new_topic),
    path("api/new_topic/", views.api_new_topic),

    # HISTORY
    path("api/record_history", views.api_record_history),
    path("api/record_history/", views.api_record_history),

    # DETAIL
    path("api/record_detail", views.api_record_detail),
    path("api/record_detail/", views.api_record_detail),

    # DELETE TOPIC
    path("api/delete_topic", views.api_delete_topic),
    path("api/delete_topic/", views.api_delete_topic),
]
