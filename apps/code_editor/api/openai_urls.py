from django.urls import path
from . import openai_views

urlpatterns = [
    # OpenAI-compatible endpoints
    path('models', openai_views.openai_models, name='openai_models'),
    path('chat/completions', openai_views.openai_chat_completions, name='openai_chat_completions'),
    path('completions', openai_views.openai_completions, name='openai_completions'),
    path('embeddings', openai_views.openai_embeddings, name='openai_embeddings'),
]
