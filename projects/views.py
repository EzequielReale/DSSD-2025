from django.http import JsonResponse
from ProjectPlanning.decorators import require_user_passes_test
from django.shortcuts import render, get_object_or_404
from .models import Project, RequestStatus
from .forms import StageForm, ObservationForm

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
        {"projects": projects_qs},
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
    else:
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
                "title": n.title,
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
    }
    return render(request, "projects/project_detail.html", context)