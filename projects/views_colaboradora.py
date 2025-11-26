from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from ProjectPlanning.decorators import require_user_passes_test

from .models import CollaborationRequest, RequestStatus
from .views import _wants_json, is_ong_colaboradora
from integrations.bonita_client import BonitaClient

client_colaboradora = BonitaClient(role="COLABORADORA")


@require_user_passes_test(is_ong_colaboradora)
def needs(request):
    """
    /needs/?format=json[&type=ECON|MAT|MO|OTRO][&include_all=1] → JSON de necesidades
    /needs/?[&type=ECON|MAT|MO|OTRO][&include_all=1] → HTML con necesidades
    """
    f_type = request.GET.get("type")
    f_include_all = request.GET.get("include_all") in ("1", "true", "True")

    try:
        q = CollaborationRequest.objects.select_related("project")

        if f_type:
            q = q.filter(request_type=f_type)

        if not f_include_all:
            q = q.filter(status=RequestStatus.OPEN)

    except Exception as e:
        messages.error(request, f"Error al consultar la base de datos: {e}")
        q = CollaborationRequest.objects.none()

    if _wants_json(request):
        try:
            response_data = []
            for item in q:
                response_data.append({
                    "project_name": item.project.name,
                    "project_id": item.project.id,
                    "type": item.request_type,
                    "description": item.description,
                    "amount": float(item.target_qty),
                    "needs_help": item.needs_help,
                    "is_fulfilled": item.status == RequestStatus.COMPLETED,
                })
            return JsonResponse(response_data, safe=False)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    filter_values = {
        "type": f_type,
        "include_all": f_include_all,
    }

    return render(request, "projects/needs.html", {
        "needs_list": q,
        "filters": filter_values,
    })


# TODO: más adelante
# - reservar necesidad (aceptar colaboración)
# - marcar necesidad como completada
# - tal vez ver observaciones relacionadas al proyecto donde colabora
