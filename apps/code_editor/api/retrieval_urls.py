"""URL patterns for retrieval views."""

from django.urls import path
from . import retrieval_views

app_name = 'retrieval'

urlpatterns = [
    path('search/', retrieval_views.search_chunks, name='search_chunks'),
    path('context/', retrieval_views.get_chunk_context, name='get_chunk_context'),
    path('files/', retrieval_views.search_files, name='search_files'),
]
