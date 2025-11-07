from django.urls import path
from . import views

app_name = 'projects'
urlpatterns = [
    path('new/', views.project_create, name='project_create'),
    path('success/', views.project_success, name='project_success'),
    path('projects/', views.projects, name='projects_list'),
    path("projects/<int:project_id>/", views.project_detail, name="project_detail"),
    path("projects/<int:project_id>/add_stage/", views.add_stage, name="add_stage"),
    path("projects/<int:project_id>/add_observation/", views.add_observation, name="add_observation"),
    path('needs/', views.needs, name='needs'),
    path('notify-ongs/', views.notify_ongs, name="notify_ongs"),
    path('notifications/', views.notifications, name="notifications"),
]
