from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/", admin.site.urls),

    path("", include(("projects.urls", "projects"), namespace="projects")),

    path("auth/login/",   views.login_page,   name="login_page"),
    path("auth/login/submit/", views.login_submit, name="login_submit"),
    path("auth/refresh/", views.refresh_access, name="refresh_access"),
    path("auth/logout/",  views.logout_view,  name="logout"),

    # Health
    path("health/", views.health),

    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/", include("projects.api.urls")),
]

handler404 = views.handler404
handler500 = views.handler500
handler403 = views.handler403
handler400 = views.handler400