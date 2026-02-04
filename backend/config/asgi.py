import os
import django

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

# 1) Set settings module sớm
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# 2) Setup Django sớm
django.setup()

# 3) Import routing SAU khi setup
import chatapp.routing
import vitranslation.virecord.routing
import viassistant.routing
django_asgi_app = get_asgi_application()

# 4) Gộp tất cả WebSocket routes
websocket_urlpatterns = (
    chatapp.routing.websocket_urlpatterns
    + vitranslation.virecord.routing.websocket_urlpatterns
    + viassistant.routing.websocket_urlpatterns
)

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
