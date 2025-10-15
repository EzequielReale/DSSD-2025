from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.http import JsonResponse

def health(_):
    return JsonResponse({"status": "ok"})

def home(request):
    return render(request, "home.html")

urlpatterns = [
    path('', home, name='home'),
    path('admin/', admin.site.urls),
    path('projects/', include('projects.urls')),

    # --- Healthcheck ---
    path("health/", health),
    # --- OpenAPI/Swagger ---
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    # --- JWT ---
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    path('api/', include('projects.api.urls'))
]
