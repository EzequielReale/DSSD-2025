import json
import time
from decimal import Decimal

from django.conf import settings
from django.forms import formset_factory
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.http import JsonResponse, Http404
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q
from django.utils.dateformat import format as dfmt
from django.contrib.auth.decorators import user_passes_test

from ProjectPlanning.decorators import require_user_passes_test


from .forms import ProjectModelForm, NeedItemForm, StageForm, ObservationForm
from .models import Project, CollaborationRequest, Stage, Observation, RequestStatus
from integrations.bonita_client import BonitaClient
from .services import ProjectService

service = ProjectService()

def _wants_json(request):
    """
    Devuelve True si el cliente pidió JSON explícitamente:
    - parámetro ?format=json
    - header Accept: application/json
    """
    return (
            request.GET.get("format") == "json"
            or "application/json" in (request.headers.get("Accept") or "")
    )


def is_ong_solicitante(user):
    """Verifica si el usuario está en el grupo 'ONG solicitante'."""
    return (
            user.is_authenticated
            and user.groups.filter(name='ONG solicitante').exists()
    )


def is_ong_colaboradora(user):
    """Verifica si el usuario está en el grupo 'ONGs colaboradoras'."""
    return (
            user.is_authenticated
            and user.groups.filter(name='ONGs colaboradoras').exists()
    )


def is_consejo_directivo(user):
    """Verifica si el usuario está en el grupo 'Consejo Directivo'."""
    return (
            user.is_authenticated
            and user.groups.filter(name='Consejo Directivo').exists()
    )

def is_solicitante_o_consejo(user):
    return is_ong_solicitante(user) or is_consejo_directivo(user)

@require_user_passes_test(is_solicitante_o_consejo)
def projects_list(request):
    """
    Listado de proyectos.
    - ONG solicitante: solo los que creó ese usuario
    - Consejo Directivo: todos los proyectos
    /projects/ → HTML
    """
    if _wants_json(request):
        return JsonResponse({"error": "Endpoint JSON obsoleto"}, status=400)

    # Si es Consejo Directivo ve todos, si no solo los propios
    if is_consejo_directivo(request.user):
        projects_qs = Project.objects.all().order_by("-id")
    else:
        projects_qs = Project.objects.filter(
            created_by_user=request.user
        ).order_by("-id")

    return render(
        request,
        "projects/projects.html",
        {"projects": projects_qs,
        "is_consejo": is_consejo_directivo(request.user),
        },
    )


@require_user_passes_test(is_solicitante_o_consejo)
def project_detail(request, project_id: int):
    """
    /projects/<id>/ → HTML
    /projects/<id>/?format=json[&all=1] → JSON con detalle + necesidades

    - ONG solicitante: solo puede ver proyectos creados por ese usuario
    - Consejo Directivo: puede ver cualquier proyecto
    """
    if is_consejo_directivo(request.user):
        project = get_object_or_404(Project, pk=project_id)
    else:  # ONG solicitante
        project = get_object_or_404(
            Project,
            pk=project_id,
            created_by_user=request.user,
        )

    include_all = request.GET.get("all") in ("1", "true", "True")

    q_needs = project.requests.all()
    if not include_all:
        q_needs = q_needs.filter(status=RequestStatus.OPEN)

    # --- RESPUESTA JSON ---
    if _wants_json(request):
        def fmt(d): return dfmt(d, "Y-m-d") if d else ""
        payload = {
            "id": project.id,
            "name": project.name,
            "description": project.description or "",
            "start_date": fmt(project.start_date),
            "end_date": fmt(project.end_date),
            "needs": [{
                "type": n.request_type,
                "description": n.description,
                "amount": float(n.target_qty),
                "is_fulfilled": n.status == RequestStatus.COMPLETED,
                "needs_help": n.needs_help,
            } for n in q_needs],
        }
        return JsonResponse(payload, safe=False)

    try:
        stages = project.stages.all()
        observations = project.observations.all()
    except Exception as e:
        messages.error(request, f"Error al consultar la base de datos: {e}")
        stages = []
        observations = []

    context = {
        "project_id": project.id,
        "project": project,
        "stages": stages or [],
        "observations": observations or [],
        "stage_form": StageForm(),
        "observation_form": ObservationForm(),
        "needs_list": q_needs,
        "include_all_needs": include_all,
        "is_consejo": is_consejo_directivo(request.user),
        "is_creador": (request.user == project.created_by_user)
    }
    return render(request, "projects/project_detail.html", context)

# @login_required
# def project_detail(request, project_id):
#     """
#     Detalle completo.
#     Usa el servicio para mezclar datos locales con datos de Bonita.
#     """
#     full_project = service.get_full_project(project_id)
    
#     if not full_project:
#         messages.error(request, "El proyecto no existe.")
#         return redirect('projects:projects_list')

#     project = full_project['local']
#     needs_remote = full_project['needs'] # Esta es la lista que vino de Bonita

#     stage_form = StageForm()
#     observation_form = ObservationForm()

#     return render(request, "projects/project_detail.html", {
#         "project": project,
#         "needs_list": needs_remote,
#         "stages": project.stages.all(),
#         "observations": project.observations.all(),
#         "stage_form": stage_form,
#         "observation_form": observation_form,
#         # Permisos
#         "is_consejo": is_consejo_directivo(request.user),
#         "is_creador": (request.user == project.created_by_user)
#     })


