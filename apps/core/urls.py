from django.urls import path
from .views import live, ready

urlpatterns = [
    path('live/', live, name='core-live'),
    path('ready/', ready, name='core-ready'),
]
