from functools import wraps
from django.core.exceptions import PermissionDenied
from django.contrib.auth.views import redirect_to_login
from django.conf import settings

def require_user_passes_test(test_func):
    """
    Decorador que requiere que el usuario esté autenticado y cumpla un test dado.

    - Si el usuario NO está autenticado → redirige al LOGIN_URL.
    - Si el usuario SÍ está autenticado pero NO pasa el test → lanza PermissionDenied (403).
    - Si pasa el test → ejecuta la vista normalmente.

    Ejemplo:
        @require_user_passes_test(lambda u: u.groups.filter(name='ONG solicitante').exists())
        def project_create(request): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(
                    request.get_full_path(),
                    settings.LOGIN_URL
                )
            if not test_func(user):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
