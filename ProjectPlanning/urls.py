from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/", admin.site.urls),

    path("", include(("projects.urls", "projects"), namespace="projects")),
    path("auth/login/",  auth_views.LoginView.as_view(template_name="login.html"), name="login"),
    path("auth/logout/", auth_views.LogoutView.as_view(next_page="home"), name="logout"),
]

handler404 = views.handler404
handler500 = views.handler500
handler403 = views.handler403
handler400 = views.handler400