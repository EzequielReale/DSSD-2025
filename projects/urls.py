from django.urls import path
from . import views

app_name = 'projects'
urlpatterns = [
    path('new/', views.project_create, name='project_create'),
    path('success/', views.project_success, name='project_success'),
]
