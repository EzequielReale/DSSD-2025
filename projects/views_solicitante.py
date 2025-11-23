import json
import time
from decimal import Decimal

from django.conf import settings
from django.forms import formset_factory
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.utils.dateformat import format as dfmt
from django.utils import timezone

from ProjectPlanning.decorators import require_user_passes_test

from .forms import ProjectModelForm, NeedItemForm, StageForm
from .models import Project, CollaborationRequest, Observation
from integrations.bonita_client import BonitaClient
from .views import is_ong_solicitante
from .services import ProjectService

service = ProjectService()


@require_user_passes_test(is_ong_solicitante)
@require_http_methods(["GET", "POST"])
def project_create(request):
    """
    Alta de proyecto por parte de la ONG solicitante (con necesidades).
    """
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
        necesidades.append({
            "tipo": f.get("need_type"),
            "detalle": f.get("need_description"),
            "cantidad": f.get("quantity"),
            "ayuda": bool(f.get("needs_help")),
        })

    if not necesidades:
        return render(
            request,
            "projects/project_form.html",
            {
                "form": form,
                "formset": formset,
                "error_msg": "Debe indicar al menos una necesidad.",
            },
        )

    client = None
    case_id = None
    project = None

    try:
        with transaction.atomic():
            client = BonitaClient(role="SOLICITANTE")
            project = form.save(commit=False)
            project.created_by_ong = form.cleaned_data.get("created_by_ong") or "ONG Demo"
            project.created_by_user = request.user
            project.save()

            for n_data in necesidades:
                CollaborationRequest.objects.create(
                    project=project,
                    title=n_data.get("detalle", "Sin título")[:200],
                    description=n_data.get("detalle"),
                    request_type=n_data.get("tipo"),
                    target_qty=n_data.get("cantidad", 0),
                    needs_help=n_data.get("ayuda", False),
                )

            needs_with_help = []
            for n_data in necesidades:
                if not n_data.get("ayuda"):
                    continue
                needs_with_help.append({
                    "title": (n_data.get("detalle") or "Sin título")[:200],
                    "description": n_data.get("detalle"),
                    "request_type": n_data.get("tipo"),
                    "target_qty": str(n_data.get("cantidad") or "0"),
                })

            necesidades_json = json.dumps(needs_with_help, ensure_ascii=False)

            pid = client.get_process_id(
                settings.BONITA_PROCESS_NAME,
                settings.BONITA_PROCESS_VERSION,
            )
            inst = client.start_process(pid)
            case_id = inst.get("caseId") or inst.get("id")

            client.set_case_var(case_id, "idProyecto", project.id, "java.lang.Long")
            client.set_case_var(case_id, "colaboracionesSolicitadas",
                                len(needs_with_help), "java.lang.Integer")
            client.set_case_var(case_id, "necesidadesJson",
                                necesidades_json, "java.lang.String")


            uid = client.get_session_user_id()
            ok = client.execute_task_with_retry(case_id, "Crear proyecto en la app", uid)
            if not ok:
                msg = "Error al ejecutar la tarea 'Crear proyecto en la app'."
                raise RuntimeError(msg)

            cloud_ok, err = client.wait_for_cloud_sync(case_id, "cloudSyncOk")

            if not cloud_ok:
                raise RuntimeError("Falló sincronizando necesidades")

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

    request.session["submitted"] = {"project_id": project.id, "bonita_error": None}
    return redirect("projects:project_success")


@require_user_passes_test(is_ong_solicitante)
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
        "needs": needs,
    }
    return render(request, "projects/project_success.html", context)


@require_user_passes_test(is_ong_solicitante)
@require_http_methods(["POST"])
def add_stage(request, project_id: int):
    """
    ONG solicitante agrega una etapa al proyecto.
    """
    project = get_object_or_404(
        Project,
        pk=project_id,
        created_by_user=request.user,
    )
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


@require_user_passes_test(is_ong_solicitante)
@require_http_methods(["POST"])
def resolve_observation(request, observation_id: int):
    """
    ONG solicitante marca una observación como resuelta.
    """
    obs = get_object_or_404(
        Observation.objects.select_related("project"),
        pk=observation_id,
        project__created_by_user=request.user,
    )

    if not obs.is_resolved:
        obs.is_resolved = True
        obs.resolved_at = timezone.now()
        obs.save()
        messages.success(request, "Observación marcada como resuelta.")
    else:
        messages.info(request, "La observación ya estaba resuelta.")

    return redirect("projects:project_detail", project_id=obs.project_id)
