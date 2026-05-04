from django.urls import path
from .consumers import TaskStatusConsumer

websocket_urlpatterns = [
    path('ws/code-editor/status/', TaskStatusConsumer.as_asgi()),
]
