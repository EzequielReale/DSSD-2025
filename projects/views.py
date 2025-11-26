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

from .forms import ProjectModelForm, NeedItemForm, StageForm, ObservationForm
from .models import Project, CollaborationRequest, Stage, Observation, RequestStatus
from integrations.bonita_client import BonitaClient
from .services import ProjectService

service = ProjectService()

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

            # for n_data in necesidades:
            #     CollaborationRequest.objects.create(
            #         project=project,
            #         title=n_data.get("detalle", "Sin título")[:200],
            #         description=n_data.get("detalle"),
            #         request_type=n_data.get("tipo"),
            #         target_qty=n_data.get("cantidad", 0),
            #         needs_help=n_data.get("ayuda", False)
            #     )

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
                client.execute_task(task["id"], "Crear proyecto en la app", uid)

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
    """Catálogo local. Muy rápido."""
    projects_list = Project.objects.all()
    return render(request, "projects/projects.html", {
        "projects": projects_list,
        "is_consejo": is_consejo_directivo(request.user),
        })

@login_required
def project_detail(request, project_id):
    """
    Detalle completo.
    Usa el servicio para mezclar datos locales con datos de Bonita.
    """
    full_project = service.get_full_project(project_id)
    
    if not full_project:
        messages.error(request, "El proyecto no existe.")
        return redirect('projects:projects_list')

    project = full_project['local']
    needs_remote = full_project['needs'] # Esta es la lista que vino de Bonita

    stage_form = StageForm()
    observation_form = ObservationForm()

    return render(request, "projects/project_detail.html", {
        "project": project,
        "needs_list": needs_remote,
        "stages": project.stages.all(),
        "observations": project.observations.all(),
        "stage_form": stage_form,
        "observation_form": observation_form,
        # Permisos
        "is_consejo": is_consejo_directivo(request.user),
        "is_creador": (request.user == project.created_by_user)
    })

@login_required
@user_passes_test(is_consejo_directivo)
def start_monitoring(request, project_id):
    """
    Inicia el proceso de Monitoreo para un proyecto específico.
    """
    project = get_object_or_404(Project, pk=project_id)
    
    # Si ya tiene uno activo, no iniciamos otro
    if project.monitoring_case_id:
        messages.warning(request, "Ya existe una sesión de monitoreo activa para este proyecto.")
        return redirect('projects:project_detail', project_id=project.id)

    client = service.bonita
    try:
        case_id = client.start_process_with_contract(
            "Monitoreo", 
            settings.BONITA_PROCESS_VERSION,
            {}
        )
        
        payload = {
            "idProyectoInput": project.id,
            "aprobadoInput": False,
            "emailConsejoInput": request.user.email,
            "emailOngInput": project.created_by_user.email,
        }
        
        while True:
            success = client.execute_bonita_task(
                case_id,
                "Revisión de proyectos",
                client.get_session_user_id(),
                payload
            )
            
            if success:
                project.monitoring_case_id = case_id
                project.save()
                break
    
            # Si no la encontró, esperamos un poco antes de volver a preguntar
            time.sleep(0.5) 

        if success:
            messages.success(request, "Sesión iniciada y tarea auto-completada.")
        else:
            messages.warning(request, "El proceso inició, pero la tarea tardó demasiado en aparecer.")
    
    except Exception as e:
        messages.error(request, f"Error al iniciar monitoreo: {e}")
    
    time.sleep(1)
    return redirect('projects:project_detail', project_id=project.id)


@login_required
@user_passes_test(is_ong_colaboradora, login_url=None)
def needs(request):
    """
    Dashboard global de necesidades pendientes.
    Trae todo de Bonita en tiempo real.
    """
    pending_needs = service.get_all_pending_needs()
    return render(request, "projects/needs.html", {"requests": pending_needs})


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
    
    if project.has_monitoring:
        messages.error(request, "El proyecto ya tiene una observación cargada.")
        return redirect("projects:project_detail", project_id=project_id)
    
    if form.is_valid():
        try:
            observation = form.save(commit=False)
            observation.project = project
            observation.observer_label = f"{request.user.username}"
            observation.save()
            project.has_monitoring = True
            project.save()

            client = service.bonita
            success = client.execute_bonita_task(
                    case_id=project.monitoring_case_id,
                    task_name="Enviar informe de sugerencias",
                    user_id=client.get_session_user_id(),
                )
            messages.success(request, "Observación agregada correctamente.")
        except Exception as e:
            messages.error(request, f"Error al guardar la observación: {e}")
    else:
        messages.error(request, "El formulario de observación contenía errores.")

    return redirect("projects:project_detail", project_id=project_id)

@login_required
@user_passes_test(is_ong_solicitante)
@require_http_methods(["POST"])
def fix_observation(request, project_id: int, observation_id: int):
    """
    Resuelve una observación.
    """
    try:
        observation = get_object_or_404(Observation, pk=observation_id)
        project = observation.project
        
        client = service.bonita
        success = client.execute_bonita_task(
            case_id=observation.project.monitoring_case_id,
            task_name="Resolver problemas",
            user_id=client.get_session_user_id(),
        )

        observation.resolved = True
        observation.save()
        project.monitoring_case_id = None
        project.has_monitoring = False
        project.save()
        
        messages.success(request, "Observación resuelta correctamente.")
    except Exception as e:
        messages.error(request, f"Error al resolver la observación: {e}")

    return redirect("projects:project_detail", project_id=project_id)
