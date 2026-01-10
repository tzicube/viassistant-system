from django.urls import path
from .views import chat ,create_conversation , list_conversations ,conversation_detail

urlpatterns = [
    path("api/chat", chat),
    path("api/creatnew", create_conversation ),
    path("api/conversations", list_conversations), 
    path("api/conversations/<int:conversation_id>/", conversation_detail),
]