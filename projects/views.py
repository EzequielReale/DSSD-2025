import json
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

from .forms import ProjectModelForm, NeedItemForm, StageForm, ObservationForm
from .models import Project, CollaborationRequest, Stage, Observation, RequestStatus
from integrations.bonita_client import BonitaClient


def _wants_json(request):
    return (
            request.GET.get("format") == "json"
            or "application/json" in (request.headers.get("Accept") or "")
    )

def is_ong_solicitante(user):
    """Verifica si el usuario está en el grupo 'ONG solicitante'"""
    if user.is_authenticated:
        return user.groups.filter(name='ONG solicitante').exists()
    return False

def is_ong_colaboradora(user):
    """Verifica si el usuario está en el grupo 'ONGs colaboradoras'"""
    if user.is_authenticated:
        return user.groups.filter(name='ONGs colaboradoras').exists()
    return False

def is_consejo_directivo(user):
    """Verifica si el usuario está en el grupo 'Consejo Directivo'"""
    if user.is_authenticated:
        return user.groups.filter(name='Consejo Directivo').exists()
    return False

@login_required
@user_passes_test(is_ong_solicitante)
@require_http_methods(["GET", "POST"])
def project_create(request):
    NeedFormSet = formset_factory(
        NeedItemForm, extra=0, can_delete=True, min_num=1, validate_min=True
    )

    if request.method == "GET":
        return render(
            request,
            "projects/project_form.html",
            {
                "form": ProjectModelForm(),
                "formset": NeedFormSet(prefix="needs", initial=[{}]),
                "error_msg": None,
            },
        )

    form = ProjectModelForm(request.POST)
    formset = NeedFormSet(request.POST, prefix="needs")

    if not (form.is_valid() and formset.is_valid()):
        return render(
            request,
            "projects/project_form.html",
            {"form": form, "formset": formset, "error_msg": None},
        )

    necesidades = []
    for f in formset.cleaned_data:
        if not f or f.get("DELETE"):
            continue
        tipo = f.get("need_type")
        cantidad = f.get("quantity")
        necesidades.append({
            "tipo": tipo,
            "detalle": f.get("need_description"),
            "cantidad": cantidad, # El modelo maneja Decimal
            "ayuda": bool(f.get("needs_help")),
        })

    if not necesidades:
        return render(
            request,
            "projects/project_form.html",
            {"form": form, "formset": formset,
             "error_msg": "Debe indicar al menos una necesidad."},
        )

    client = None
    case_id = None
    project = None

    try:
        with transaction.atomic():
            project = form.save(commit=False)
            project.created_by_ong = form.cleaned_data.get("created_by_ong") or "ONG Demo"
            project.created_by_user = request.user
            project.save()

            for n_data in necesidades:
                CollaborationRequest.objects.create(
                    project=project,
                    title=n_data.get("detalle", "Sin título")[:200], # Usar max_length del modelo
                    description=n_data.get("detalle"),
                    request_type=n_data.get("tipo"),
                    target_qty=n_data.get("cantidad", 0),
                    # El status por defecto es OPEN
                )

            # --- Interacción con Bonita BPM ---
            client = BonitaClient()
            process_id = getattr(settings, "BONITA_PROCESS_ID", None) or client.get_process_id(
                settings.BONITA_PROCESS_NAME, settings.BONITA_PROCESS_VERSION
            )

            inst = client.start_process(process_id)
            case_id = (
                    inst.get("caseId")
                    or inst.get("processInstanceId")
                    or inst.get("id")
            )
            
            client.set_case_var(case_id, "idProyecto", int(project.id), "java.lang.Long")
            client.set_case_var(case_id, "colaboracionesSolicitadas", len(necesidades), "java.lang.Integer")
            tasks = client.find_ready_user_tasks(case_id)
            if tasks:
                task = next(
                    (t for t in tasks if t.get("displayName") == "Crear proyecto en la app"),
                    tasks[0],
                )
                uid = client.get_session_user_id()
                client.assign_task(task["id"], uid)
                client.execute_task(task["id"])

            project.bonita_case_id = case_id
            project.save(update_fields=["bonita_case_id"])

    except Exception as e:
        try:
            if client and case_id:
                client.abort_case(case_id)
        except Exception:
            pass
        return render(
            request,
            "projects/project_form.html",
            {
                "form": form,
                "formset": formset,
                "error_msg": (
                        "No se pudo completar la operación (BD/Bonita). "
                        "Intente más tarde o contacte al administrador. " + str(e)
                ),
            },
        )

    # Éxito
    request.session["submitted"] = {"project_id": project.id, "bonita_error": None}
    return redirect("projects:project_success")


@login_required
@user_passes_test(is_ong_solicitante)
def project_success(request):
    data = request.session.get("submitted")
    if not data:
        return redirect("projects:project_create")

    project = Project.objects.filter(pk=data.get("project_id")).first()    
    
    if not project:
        return redirect("projects:project_create")
    
    needs = project.requests.all()

    context = {
        "project": project, 
        "bonita_error": data.get("bonita_error"),
        "needs": needs # Pasamos las necesidades locales
    }
    return render(request, "projects/project_success.html", context)

@login_required
def projects(request):
    """
    /projects/?format=json → JSON con lista de proyectos
    /projects/ → HTML con lista de proyectos
    """
    if _wants_json(request):
        return JsonResponse({"error": "Endpoint JSON obsoleto"}, status=400)

    projects_list = Project.objects.all()
    
    return render(request, "projects/projects.html", {
        "projects": projects_list
    })

@login_required
@user_passes_test(is_ong_colaboradora)
@login_required
def needs(request):
    """
    /needs/?format=json[&type=ECON|MAT|MO|OTRO][&include_all=1] → JSON de necesidades
    /needs/?[&type=ECON|MAT|MO|OTRO][&include_all=1] → HTML con necesidades
    """
    
    f_type = request.GET.get('type')
    f_include_all = request.GET.get('include_all') in ('1', 'true', 'True')

    try:
        q = CollaborationRequest.objects.select_related('project')
        
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
                    "needs_help": True, # Asumimos, o agregamos el campo al modelo
                    "is_fulfilled": item.status == RequestStatus.COMPLETED,
                })
            return JsonResponse(response_data, safe=False)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    
    # Para mantener los valores de los filtros en el formulario
    filter_values = {
        'type': f_type,
        'include_all': f_include_all,
    }
    
    return render(request, "projects/needs.html", {
        "needs_list": q,
        "filters": filter_values
    })


@login_required
def project_detail(request, project_id: int):
    """
    /proyectos/<id>/ → HTML
    /proyectos/<id>/?format=json[&include_all=1] → JSON con detalle + necesidades
    """
    project = get_object_or_404(Project, pk=project_id)
    
    include_all = request.GET.get("all") in ("1", "true", "True")
    
    q_needs = project.requests.all()
    if not include_all:
        q_needs = q_needs.filter(status=RequestStatus.OPEN)

    # --- RESPUESTA JSON (Sin cambios) ---
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
                "needs_help": True, # Asumimos, o agregamos el campo al modelo
            } for n in q_needs]
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
        "needs_list": q_needs, # Pasamos la lista de necesidades
        "include_all_needs": include_all, # Para el link de "ver todas/solo abiertas"
    }
    return render(request, "projects/project_detail.html", context)


@login_required
@user_passes_test(is_ong_solicitante)
@require_http_methods(["POST"])
def add_stage(request, project_id: int):
    project = get_object_or_404(Project, pk=project_id)
    form = StageForm(request.POST) 
    
    if form.is_valid():
        try:
            stage = form.save(commit=False)
            stage.project = project
            stage.save()
            messages.success(request, "Etapa agregada correctamente.")
        except Exception as e:
            messages.error(request, f"Error al guardar la etapa: {e}")
    else:
        messages.error(request, "El formulario de etapa contenía errores.")
        
    return redirect("projects:project_detail", project_id=project_id)


@login_required
@user_passes_test(is_consejo_directivo)
@require_http_methods(["POST"])
def add_observation(request, project_id: int):
    project = get_object_or_404(Project, pk=project_id)
    form = ObservationForm(request.POST)
    
    if form.is_valid():
        try:
            observation = form.save(commit=False)
            observation.project = project
            observation.save()
            messages.success(request, "Observación agregada correctamente.")
        except Exception as e:
            messages.error(request, f"Error al guardar la observación: {e}")
    else:
        messages.error(request, "El formulario de observación contenía errores.")

    return redirect("projects:project_detail", project_id=project_id)
    

# @csrf_exempt
# def notify_ongs(request):
#     """
#     (Sin cambios, esta vista es interna/bonita)
#     """
#     if request.method != "POST":
#         return JsonResponse({"error": "Método inválido"}, status=405)
#     # ... (resto del código sin cambios)
#     try:
#         data = json.loads(request.body.decode("utf-8"))
#         project_name = data.get("projectName") or "Proyecto sin nombre"
#         summary = data.get("summary") or "Nueva solicitud de colaboración."
# 
#         Notification.objects.create(
#             title=f"Nuevo proyecto: {project_name}",
#             message=summary
#         )
# 
#         return JsonResponse({"ok": True})
#     except Exception as e:
#         return JsonResponse({"error": str(e)}, status=400)


# @login_required
# def notifications(request):
#     """
#     (Sin cambios, esta vista es interna)
#     """
#     nots = Notification.objects.order_by("-created_at")[:10]
#     # ... (resto del código sin cambios)
#     data = [
#         {
#             "title": n.title,
#             "message": n.message,
#             "created_at": n.created_at.strftime("%d/%m/%Y %H:%M"),
#         }
#         for n in nots
#     ]
#     return JsonResponse(data, safe=False)