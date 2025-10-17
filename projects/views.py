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

from .forms import ProjectModelForm, NeedItemForm
from .models import Project, Need, Notification
from integrations.bonita_client import BonitaClient

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

    try:
        with transaction.atomic():
            project = form.save(commit=False)
            project.created_by_ong = form.cleaned_data.get("created_by_ong") or "ONG Demo"
            project.save()

            for n in necesidades:
                Need.objects.create(
                    project=project,
                    type=n["tipo"],
                    description=n["detalle"],
                    amount=Decimal(str(n["cantidad"])),
                    needs_help=bool(n["ayuda"]),
                    is_fulfilled=False,
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
    data = request.session.get("submitted")
    if not data:
        return redirect("projects:project_create")

    project = (
        Project.objects.prefetch_related("needs_rel")
        .filter(pk=data.get("project_id"))
        .first()
    )
    if not project:
        return redirect("projects:project_create")

    context = {"project": project, "bonita_error": data.get("bonita_error")}
    return render(request, "projects/project_success.html", context)


@login_required
def projects(request):
    """
    /proyectos/ → HTML
    /proyectos/?format=json → JSON con totales de necesidades
    """
    if _wants_json(request):
        qs = (
            Project.objects
            .annotate(
                needs_total=Count("needs_rel"),
                needs_fulfilled=Count("needs_rel", filter=Q(needs_rel__is_fulfilled=True)),
                needs_open=Count("needs_rel", filter=Q(needs_rel__is_fulfilled=False)),
            )
            .order_by("-id")
        )

        def fmt(d): return dfmt(d, "Y-m-d") if d else ""
        data = [{
            "id": p.id,
            "name": p.name,
            "start_date": fmt(p.start_date),
            "end_date": fmt(p.end_date),
            "needs_total": p.needs_total or 0,
            "needs_open": p.needs_open or 0,
            "needs_fulfilled": p.needs_fulfilled or 0,
        } for p in qs[:500]]
        return JsonResponse(data, safe=False)

    return render(request, "projects/projects.html")


@login_required
def needs(request):
    """
    /needs/ → HTML
    /needs/?format=json[&type=ECON|MAT|MO|OTRO][&include_all=1] → JSON de necesidades
    """
    if _wants_json(request):
        q = Need.objects.select_related('project').all()

        t = request.GET.get('type')
        include_all = request.GET.get('include_all') in ('1', 'true', 'True')

        if t:
            q = q.filter(type=t)
        if not include_all:
            q = q.filter(Q(needs_help=True) | Q(is_fulfilled=False))

        data = [{
            "project_name": n.project.name if n.project_id else "",
            "project_id": n.project_id,
            "type": n.type,
            "description": n.description,
            "amount": float(n.amount) if n.amount is not None else None,
            "needs_help": bool(n.needs_help),
            "is_fulfilled": bool(n.is_fulfilled),
        } for n in q.order_by("-id")[:500]]

        return JsonResponse(data, safe=False)

    return render(request, "projects/needs.html")


@login_required
def project_detail(request, project_id: int):
    """
    /proyectos/<id>/ → HTML
    /proyectos/<id>/?format=json[&include_all=1] → JSON con detalle + necesidades
    """
    if _wants_json(request):
        p = (
            Project.objects
            .prefetch_related("needs_rel")
            .filter(pk=project_id)
            .first()
        )
        if not p:
            raise Http404("Proyecto no encontrado")

        include_all = request.GET.get("include_all") in ("1", "true", "True")

        needs_qs = p.needs_rel.all()
        if not include_all:
            needs_qs = needs_qs.filter(Q(needs_help=True) | Q(is_fulfilled=False))

        def fmt(d): return dfmt(d, "Y-m-d") if d else ""

        payload = {
            "id": p.id,
            "name": p.name,
            "description": p.description or "",
            "start_date": fmt(p.start_date),
            "end_date": fmt(p.end_date),
            "needs": [{
                "type": n.type,
                "description": n.description,
                "amount": float(n.amount) if n.amount is not None else None,
                "is_fulfilled": bool(n.is_fulfilled),
                "needs_help": bool(n.needs_help),
            } for n in needs_qs.order_by("-id")]
        }
        return JsonResponse(payload, safe=False)

    return render(request, "projects/project_detail.html", {"project_id": project_id})

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