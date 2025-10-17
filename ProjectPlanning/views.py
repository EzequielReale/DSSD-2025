from django.shortcuts import render
from django.http import JsonResponse

def home(request):
    return render(request, "home.html")

def handler404(request, exception):
    return render(request, "error.html", {"status": 404, "title": "Página no encontrada",
                                          "message": "La dirección que intentaste abrir no existe o fue movida."},
                  status=404)

def handler500(request):
    return render(request, "error.html", {"status": 500, "title": "Error del servidor",
                                          "message": "Ocurrió un error inesperado. Estamos trabajando para solucionarlo."},
                  status=500)

def handler403(request, exception):
    return render(request, "error.html", {"status": 403, "title": "Acceso denegado",
                                          "message": "No tenés permisos para ver este recurso."},
                  status=403)

def handler400(request, exception):
    return render(request, "error.html", {"status": 400, "title": "Solicitud inválida",
                                          "message": "La solicitud enviada no es válida."},
                  status=400)
