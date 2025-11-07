import json
from decimal import Decimal

from django.conf import settings
from django.forms import formset_factory
from django.shortcuts import render, redirect
from django.db import transaction
from django.http import JsonResponse, Http404
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.utils.dateformat import format as dfmt

from .forms import ProjectModelForm, NeedItemForm, StageForm, ObservationForm
from .models import Project, Notification
from integrations.bonita_client import BonitaClient
from integrations.api_client import ApiClient

def _wants_json(request):
    return (
            request.GET.get("format") == "json"
            or "application/json" in (request.headers.get("Accept") or "")
    )

@login_required
@require_http_methods(["GET", "POST"])
def project_create(request):
    NeedFormSet = formset_factory(
        NeedItemForm, extra=0, can_delete=True, min_num=1, validate_min=True
    )

    if request.method == "GET":
        # HTML
        return render(
            request,
            "projects/project_form.html",
            {
                "form": ProjectModelForm(),
                "formset": NeedFormSet(prefix="needs", initial=[{}]),
                "error_msg": None,
            },
        )

    # POST (form)
    form = ProjectModelForm(request.POST)
    formset = NeedFormSet(request.POST, prefix="needs")

    if not (form.is_valid() and formset.is_valid()):
        return render(
            request,
            "projects/project_form.html",
            {"form": form, "formset": formset, "error_msg": None},
        )

    # Construir lista de necesidades a partir del formset
    necesidades = []
    for f in formset.cleaned_data:
        if not f or f.get("DELETE"):
            continue
        tipo = f.get("need_type")
        cantidad = f.get("quantity")
        necesidades.append({
            "tipo": tipo,
            "detalle": f.get("need_description"),
            "cantidad": float(cantidad) if tipo == "ECON" else int(cantidad),
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
    api_client = ApiClient()

    try:
        with transaction.atomic():
            project = form.save(commit=False)
            project.created_by_ong = form.cleaned_data.get("created_by_ong") or "ONG Demo"
            project.save()

            # --- REFACTOR: Enviar Necesidades a la API de Cloud ---
            for n_data in necesidades:
                api_client.create_request(project.project_uuid, n_data)

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

            # Buscar y ejecutar la primera user task del proceso
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
        # rollback y abortar case en Bonita si falló
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
def project_success(request):
    # --- REFACTOR: 'needs_rel' ya no existe ---
    data = request.session.get("submitted")
    if not data:
        return redirect("projects:project_create")

    project = Project.objects.filter(pk=data.get("project_id")).first() # Solo el proyecto
    
    if not project:
        return redirect("projects:project_create")
    
    # --- Traer las "needs" de la API para el resumen ---
    try:
        api_client = ApiClient()
        needs = api_client.get_requests(project_ref=project.project_uuid)
    except Exception:
        needs = [] # Si falla la API, mostramos 0 necesidades

    context = {
        "project": project, 
        "bonita_error": data.get("bonita_error"),
        "needs": needs # Pasamos las necesidades de la API
    }
    return render(request, "projects/project_success.html", context)


@login_required
def projects(request):
    """
    /proyectos/ → HTML
    REFACTOR: El endpoint JSON se elimina o simplifica.
    Los contadores (needs_total, etc.) ya no se calculan aquí
    porque requeriría N+1 llamadas a la API.
    """
    if _wants_json(request):
        # Esta lógica ya no es viable.
        return JsonResponse({"error": "Endpoint JSON obsoleto"}, status=400)

    # El request HTML ahora solo lista los proyectos
    projects_list = Project.objects.all().order_by("-id")
    
    return render(request, "projects/projects.html", {
        "projects": projects_list
    })


@login_required
def needs(request):
    """
    /needs/ → HTML
    /needs/?format=json[&type=ECON|MAT|MO|OTRO][&include_all=1] → JSON de necesidades
    """
    if _wants_json(request):
        # --- REFACTOR: Consultar a la API de Cloud, no a la DB local ---
        # q = Need.objects.select_related('project').all() <-- SE BORRA
        
        t = request.GET.get('type')
        include_all = request.GET.get('include_all') in ('1', 'true', 'True')

        try:
            api_client = ApiClient()
            data = api_client.get_requests(type=t, include_all=include_all)
            
            if data is None: data = []

            # --- Enriquecer datos para el template ---
            # (El template JS espera project_name, is_fulfilled, needs_help)
            project_uuids = {item['project_ref'] for item in data if item.get('project_ref')}
            projects_map = {
                str(p.project_uuid): p.name 
                for p in Project.objects.filter(project_uuid__in=project_uuids)
            }
            
            response_data = []
            for item in data:
                response_data.append({
                    "project_name": projects_map.get(item.get('project_ref'), 'Proyecto Desconocido'),
                    "project_id": item.get('project_ref'), # Usamos el UUID
                    "type": item.get('request_type'),
                    "description": item.get('description'),
                    "amount": float(item.get('target_qty', 0)),
                    "needs_help": True, # Asumimos que todas las 'requests' necesitan ayuda
                    "is_fulfilled": item.get('status') == 'COMPLETED',
                })

            return JsonResponse(response_data, safe=False)
        
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return render(request, "projects/needs.html")


@login_required
def project_detail(request, project_id: int):
    """
    /proyectos/<id>/ → HTML
    /proyectos/<id>/?format=json[&include_all=1] → JSON con detalle + necesidades
    """
    # project_id es el ID (int) local
    project = get_object_or_404(Project, pk=project_id)
    
    if _wants_json(request):
        # --- REFACTOR: Traer 'needs' desde la API usando 'project_uuid' ---
        # p = Project.objects.prefetch_related("needs_rel")... <-- SE BORRA
        
        include_all = request.GET.get("include_all") in ("1", "true", "True")
        
        try:
            api_client = ApiClient()
            api_needs = api_client.get_requests(
                project_ref=project.project_uuid, 
                include_all=include_all
            )
            if api_needs is None: api_needs = []
        except Exception:
            api_needs = []

        def fmt(d): return dfmt(d, "Y-m-d") if d else ""

        payload = {
            "id": project.id,
            "name": project.name,
            "description": project.description or "",
            "start_date": fmt(project.start_date),
            "end_date": fmt(project.end_date),
            # Mapear datos de la API a lo que espera el JS
            "needs": [{
                "type": n.get('request_type'),
                "description": n.get('description'),
                "amount": float(n.get('target_qty', 0)),
                "is_fulfilled": n.get('status') == 'COMPLETED',
                "needs_help": True, # Asumimos True
            } for n in api_needs]
        }
        return JsonResponse(payload, safe=False)

    # --- Lógica para el request HTML ---
    # Traemos todo de la API para renderizar
    try:
        api_client = ApiClient()
        stages = api_client.get_stages(project.project_uuid)
        observations = api_client.get_observations(project.project_uuid)
    except Exception as e:
        messages.error(request, f"Error al contactar la API: {e}")
        stages = []
        observations = []

    context = {
        "project_id": project.id, # El JS lo necesita
        "project": project,       # El template lo necesita
        "stages": stages or [],
        "observations": observations or [],
        "stage_form": StageForm(),
        "observation_form": ObservationForm(),
    }
    return render(request, "projects/project_detail.html", context)


@login_required
@require_http_methods(["POST"])
def add_stage(request, project_id: int):
    project = get_object_or_404(Project, pk=project_id)
    form = StageForm(request.POST)
    
    if form.is_valid():
        try:
            api_client = ApiClient()
            api_client.create_stage(project.project_uuid, form.cleaned_data)
            messages.success(request, "Etapa agregada correctamente.")
        except Exception as e:
            messages.error(request, f"Error al guardar la etapa: {e}")
    else:
        messages.error(request, "El formulario de etapa contenía errores.")
        
    return redirect("projects:project_detail", project_id=project_id)


@login_required
@require_http_methods(["POST"])
def add_observation(request, project_id: int):
    project = get_object_or_404(Project, pk=project_id)
    form = ObservationForm(request.POST)
    
    if form.is_valid():
        try:
            api_client = ApiClient()
            api_client.create_observation(project.project_uuid, form.cleaned_data)
            messages.success(request, "Observación agregada correctamente.")
        except Exception as e:
            messages.error(request, f"Error al guardar la observación: {e}")
    else:
        messages.error(request, "El formulario de observación contenía errores.")

    return redirect("projects:project_detail", project_id=project_id)
    

@csrf_exempt
def notify_ongs(request):
    """
    Recibe un POST desde Bonita (tarea automática 'Enviar pedido a red de ONGs')
    y genera una notificación interna visible en Django.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método inválido"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
        project_name = data.get("projectName") or "Proyecto sin nombre"
        summary = data.get("summary") or "Nueva solicitud de colaboración."

        Notification.objects.create(
            title=f"Nuevo proyecto: {project_name}",
            message=summary
        )

        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

@login_required
def notifications(request):
    nots = Notification.objects.order_by("-created_at")[:10]
    data = [
        {
            "title": n.title,
            "message": n.message,
            "created_at": n.created_at.strftime("%d/%m/%Y %H:%M"),
        }
        for n in nots
    ]
    return JsonResponse(data, safe=False)