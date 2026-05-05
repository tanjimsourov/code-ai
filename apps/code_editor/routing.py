from django.urls import path
from .consumers import ChatStreamConsumer, TaskStatusConsumer

websocket_urlpatterns = [
    path('ws/code-editor/chat/', ChatStreamConsumer.as_asgi()),
    path('ws/code-editor/status/', TaskStatusConsumer.as_asgi()),
]
