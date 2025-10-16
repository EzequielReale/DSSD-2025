import json
from decimal import Decimal
from django.conf import settings
from django.forms import formset_factory
from django.shortcuts import render, redirect
from django.db import transaction
from django.http import JsonResponse, Http404
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .forms import ProjectModelForm, NeedItemForm
from .models import Project, Need, Notification
from integrations.bonita_client import BonitaClient
from ProjectPlanning.decorators import require_auth

@require_auth
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
            case_id = inst.get("caseId") or inst.get("processInstanceId") or inst.get("id")

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
                "error_msg": f"No se pudo completar la operación (BD/Bonita). "
                             f"Intente más tarde o contacte al administrador. {e}"
            },
        )

    # Éxito
    request.session["submitted"] = {"project_id": project.id, "bonita_error": None}
    return redirect("projects:project_success")

@require_auth
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


@require_auth
def projects(request):
    return render(request, "projects/projects.html")


@require_auth
def needs(request):
    return render(request, "projects/needs.html")


@require_auth
def project_detail(request, project_id: int):
    return render(request, "projects/project_detail.html", {"project_id": project_id})

@require_auth
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