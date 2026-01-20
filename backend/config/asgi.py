import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

# 1) Set settings module sớm
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# 2) Setup Django sớm (quan trọng để import models trong consumer không chết)
django.setup()

# 3) Import routing sau khi setup
import chatapp.routing

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(chatapp.routing.websocket_urlpatterns)
    ),
})
