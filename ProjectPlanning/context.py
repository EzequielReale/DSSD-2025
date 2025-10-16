from typing import Dict
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken

User = get_user_model()

def auth_ctx(request) -> Dict[str, object]:
    """
    Expone flags de autenticación para templates.
    No rompe si el token no existe / venció / es inválido.
    """
    token = request.COOKIES.get("access")
    out = {
        "is_authenticated": False,
        "current_username": None,
        "jwt_seconds_left": None,
    }

    if not token:
        return out

    try:
        at = AccessToken(token)
        out["is_authenticated"] = True
        exp = int(at.get("exp", 0))
        out["jwt_seconds_left"] = max(0, exp - int(at.current_time.timestamp()))

        uid = at.get("user_id")
        if uid:
            try:
                u = User.objects.only("username").get(id=uid)
                out["current_username"] = u.username
            except User.DoesNotExist:
                pass

    except Exception:
        pass

    return out