from functools import wraps
from django.shortcuts import redirect
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

def require_auth(view_func):
    """
    Si no hay cookie 'access' o está expirada/invalidada,
    redirige a /auth/login/?next=<ruta>
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        token = request.COOKIES.get("access")
        if not token:
            return redirect(f"{reverse('login_page')}?next={request.path}")

        try:
            AccessToken(token)
        except Exception:
            return redirect(f"{reverse('login_page')}?next={request.path}")

        return view_func(request, *args, **kwargs)

    return _wrapped
