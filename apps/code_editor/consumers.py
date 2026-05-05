import json
from channels.generic.websocket import AsyncWebsocketConsumer


class TaskStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        public_ws = False
        try:
            from django.conf import settings
            public_ws = bool(getattr(settings, 'CODE_EDITOR_PUBLIC_METRICS', False))
        except Exception:
            public_ws = False

        if not public_ws and (user is None or not user.is_authenticated):
            await self.close(code=4401)
            return
        await self.accept()

    async def receive(self, text_data=None, bytes_data=None):
        payload = {'type': 'ack', 'message': 'streaming scaffold active'}
        await self.send(text_data=json.dumps(payload))


class ChatStreamConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return
        await self.accept()

    async def receive(self, text_data=None, bytes_data=None):
        payload = {
            'type': 'chat_stream',
            'status': 'accepted',
            'message': 'Authenticated chat websocket scaffold active',
        }
        await self.send(text_data=json.dumps(payload))
