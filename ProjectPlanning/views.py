from django.conf import settings
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.contrib.auth import authenticate
from django.middleware import csrf
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from .decorators import require_auth
from django.urls import reverse

def health(_):
    return JsonResponse({"status": "ok"})

def home(request):
    return render(request, "home.html")

def login_page(request):
    token_str = request.COOKIES.get("access")
    if token_str:
        try:
            AccessToken(token_str)
            return redirect(request.GET.get("next") or "home")
        except Exception:
            refresh_str = request.COOKIES.get("refresh")
            if refresh_str:
                try:
                    new_access = str(RefreshToken(refresh_str).access_token)
                    resp = redirect(request.GET.get("next") or "home")
                    resp.set_cookie(
                        "access", new_access, httponly=True, samesite="Lax",
                        secure=not settings.DEBUG, max_age=60 * 60
                    )
                    return resp
                except Exception:
                    pass
    return render(request, "login.html", {"csrf_token": csrf.get_token(request)})

@require_http_methods(["POST"])
def login_submit(request):
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    user = authenticate(request, username=username, password=password)
    if not user:
        return render(request, "login.html", {"error": "Credenciales inválidas"}, status=401)

    refresh = RefreshToken.for_user(user)
    access = refresh.access_token

    resp = redirect("home")
    secure = not settings.DEBUG
    resp.set_cookie("access",  str(access),  httponly=True, samesite="Lax", secure=secure, max_age=60*60)        # ~1h
    resp.set_cookie("refresh", str(refresh), httponly=True, samesite="Lax", secure=secure, max_age=60*60*24*7)   # ~7d
    return resp

@require_http_methods(["POST"])
def refresh_access(request):
    tok = request.COOKIES.get("refresh")
    if not tok:
        return JsonResponse({"detail": "No refresh cookie"}, status=401)

    try:
        new_access = str(RefreshToken(tok).access_token)
    except Exception:
        return JsonResponse({"detail": "Refresh inválido/expirado"}, status=401)

    secure = not settings.DEBUG
    resp = JsonResponse({"ok": True})
    resp.set_cookie("access", new_access, httponly=True, samesite="Lax", secure=secure, max_age=60*60)
    return resp

@require_auth
def logout_view(request):
    resp = redirect("home")
    resp.delete_cookie("access")
    resp.delete_cookie("refresh")
    return resp

def _wants_json(request) -> bool:
    if request.path.startswith("/api/"):
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return "application/json" in accept

def _render_error(request, status: int, title: str, message: str):
    if _wants_json(request):
        return JsonResponse({"detail": message}, status=status)
    return render(request, "error.html", {
        "status": status,
        "title": title,
        "message": message,
    }, status=status)

def handler404(request, exception):
    return _render_error(request, 404, "Página no encontrada",
                         "La dirección que intentaste abrir no existe o fue movida.")

def handler500(request):
    return _render_error(request, 500, "Error del servidor",
                         "Ocurrió un error inesperado. Estamos trabajando para solucionarlo.")

def handler403(request, exception):
    return _render_error(request, 403, "Acceso denegado",
                         "No tenés permisos para ver este recurso.")

def handler400(request, exception):
    return _render_error(request, 400, "Solicitud inválida",
                         "La solicitud enviada no es válida.")

