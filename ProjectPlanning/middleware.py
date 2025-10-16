class JWTCookieMiddleware:
    """
    Si existe la cookie 'access', la inyecta como Authorization: Bearer <token>
    Así DRF SimpleJWT funciona sin tocar AUTHENTICATION_CLASSES.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        access = request.COOKIES.get("access")
        if access and not request.META.get("HTTP_AUTHORIZATION"):
            request.META["HTTP_AUTHORIZATION"] = f"Bearer {access}"
        return self.get_response(request)
