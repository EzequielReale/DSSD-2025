from decimal import Decimal
import json

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods

from ProjectPlanning.decorators import require_user_passes_test
from integrations.bonita_client import BonitaClient

from .views import is_ong_colaboradora
from .models import Project, CollaborationRequest, RequestStatus


@require_user_passes_test(is_ong_colaboradora)
@require_http_methods(["GET"])
def collab_projects(request):
    """
    Lista proyectos que tienen al menos una necesidad con estado OPEN,
    mostrando cuántas son y un resumen de los objetivos por tipo.
    """
    projects_data = []

    # Traer solo necesidades abiertas y sus proyectos
    needs = (
        CollaborationRequest.objects
        .filter(needs_help=True)
        .filter(status=RequestStatus.OPEN)
        .select_related("project")
    )

    # Agrupar por proyecto
    proj_dict = {}
    for n in needs:
        proj = n.project
        if proj.id not in proj_dict:
            proj_dict[proj.id] = {
                "project": proj,
                "needs": [],
            }
        proj_dict[proj.id]["needs"].append(n)

    # Construir lista para el template
    for proj_id, info in proj_dict.items():
        project = info["project"]
        needs_list = info["needs"]

        projects_data.append({
            "project_id": project.id,
            "project_name": project.name,
            "needs_count": len(needs_list),
            "objectives": _build_target_summary(needs_list),
        })

    projects_data.sort(key=lambda p: p["project_name"].lower())

    return render(
        request,
        "projects/collab_projects.html",
        {"projects": projects_data},
    )


def _build_target_summary(needs):
    """
    needs: iterable de CollaborationRequest asociadas a un proyecto.
    Devuelve: lista de dicts con info compacta (icono + valor).
    """
    summary = {
        "ECON": Decimal("0"),
        "MAT": Decimal("0"),
        "MO": Decimal("0"),
        "OTRO": Decimal("0"),
    }

    for n in needs:
        qty = n.target_qty or 0
        try:
            qty_dec = Decimal(str(qty))
        except Exception:
            continue

        if n.request_type == "ECON":
            summary["ECON"] += qty_dec
        elif n.request_type == "MAT":
            summary["MAT"] += qty_dec
        elif n.request_type == "MO":
            summary["MO"] += qty_dec
        else:
            summary["OTRO"] += qty_dec

    objectives = []

    if summary["ECON"] > 0:
        objectives.append({
            "type": "ECON",
            "icon": "$",
            "value": f"${summary['ECON']}",
        })
    if summary["MAT"] > 0:
        objectives.append({
            "type": "MAT",
            "icon": "📦",
            "value": f"{summary['MAT']}",
        })
    if summary["MO"] > 0:
        objectives.append({
            "type": "MO",
            "icon": "👷",
            "value": f"{summary['MO']}",
        })
    if summary["OTRO"] > 0:
        objectives.append({
            "type": "OTRO",
            "icon": "•",
            "value": f"{summary['OTRO']}",
        })

    return objectives


@require_user_passes_test(is_ong_colaboradora)
@require_http_methods(["GET"])
def collab_project_needs(request, project_id):
    """
    Muestra las necesidades del proyecto leyendo la variable de caso
    `necesidadesJson` (rellenada por los conectores On enter / On finish
    de la tarea humana 'Enviar compromiso de colaboración').
    """
    project = get_object_or_404(Project, pk=project_id)

    if not project.bonita_case_id:
        messages.error(
            request,
            "Este proyecto no tiene asociado un caso en Bonita. "
            "No se pueden recuperar las necesidades.",
        )
        return redirect("projects:collab_projects")

    case_id = str(project.bonita_case_id)
    client = BonitaClient(role="COLABORADORA")

    try:
        needs_val = client.get_case_variable(case_id, "necesidadesJson")

        if not needs_val:
            messages.warning(
                request,
                "Todavía no hay necesidades sincronizadas desde la Cloud API "
                "para este proyecto.",
            )
            needs_list = []
        else:
            # El BonitaClient ya intenta parsear JSON si es texto.
            # Por las dudas, normalizamos a list de dicts.
            if isinstance(needs_val, list):
                needs_list = needs_val
            else:
                needs_list = json.loads(needs_val)

    except Exception as e:
        messages.error(request, f"Error al consultar Bonita: {e}")
        needs_list = []

    return render(
        request,
        "projects/collab_needs.html",
        {
            "project": project,
            "project_id": project_id,
            "needs": needs_list,
        },
    )


@require_user_passes_test(is_ong_colaboradora)
@require_http_methods(["POST"])
def offer_commitment(request, project_id, request_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.bonita_case_id:
        messages.error(
            request,
            "Este proyecto no tiene asociado un caso en Bonita. "
            "No se puede registrar el compromiso.",
        )
        return redirect("projects:collab_projects")

    case_id = str(project.bonita_case_id)
    client = BonitaClient(role="COLABORADORA")

    desc = request.POST.get("description", "")
    ong = request.POST.get("ong_name", "")

    try:
        client.set_case_var(case_id,"idPedido",str(request_id),type_hint="java.lang.Integer")
        client.set_case_var(case_id,"descCompromiso",desc,type_hint="java.lang.String")
        client.set_case_var(case_id, "nombreONGColab", ong, type_hint="java.lang.String")


        user_id = client.get_session_user_id()
        ok = client.execute_task_with_retry(
            case_id,
            task_name="Enviar compromiso de colaboración",
            user_id=user_id,
        )

        cloud_ok = False
        if ok:
            try:
                cloud_ok = bool(client.get_case_variable(case_id, "cloudSyncOk"))
            except Exception:
                cloud_ok = False

        if not ok or not cloud_ok:
            messages.error(
                request,
                "No se pudo registrar el compromiso en la Cloud API. "
                "Intente nuevamente más tarde.",
            )
        else:
            messages.success(
                request,
                "Tu compromiso se registró correctamente en la Cloud API. "
                "¡Gracias por colaborar! 😊",
            )

    except Exception as e:
        messages.error(
            request,
            f"Error al registrar el compromiso en Bonita: {e}",
        )

    return redirect("projects:collab_project_needs", project_id=project_id)


@require_user_passes_test(is_ong_colaboradora)
@require_http_methods(["POST"])
def fulfill_commitment(request, project_id, commitment_id):
    """
    Tarea 'Enviar colaboración' (ONG colaboradora).

    Permite que la ONG colaboradora confirme que efectivamente
    entregó la colaboración asociada al compromiso actual.
    """
    project = get_object_or_404(Project, pk=project_id)

    if not project.bonita_case_id:
        messages.error(
            request,
            "Este proyecto no tiene asociado un caso en Bonita. "
            "No se puede marcar la colaboración como enviada.",
        )
        return redirect("projects:project_detail", project_id=project.id)

    case_id = str(project.bonita_case_id)
    client = BonitaClient(role="COLABORADORA")

    try:
        client.set_case_var(case_id, "idCompromiso", commitment_id, type_hint="java.lang.Long")
    except Exception as e:
        messages.error(
            request,
            f"No se pudo registrar el compromiso en Bonita: {e}",
        )
        return redirect("projects:project_detail", project_id=project.id)

    try:
        uid = client.get_session_user_id()
        ok = client.execute_task_with_retry(case_id, task_name="Enviar colaboración",  user_id=uid)
        if not ok:
            messages.error(
                request,
                "No se pudo completar la tarea 'Enviar colaboración' en Bonita.",
            )
            return redirect("projects:project_detail", project_id=project.id)
    except Exception as e:
        messages.error(
            request,
            f"Error al ejecutar la tarea 'Enviar colaboración' en Bonita: {e}",
        )
        return redirect("projects:project_detail", project_id=project.id)

    try:
        sync_ok, err = client.wait_for_cloud_sync(case_id, "cloudSyncOk")
        if not sync_ok:
            messages.warning(
                request,
                "La colaboración se marcó como enviada, "
                "pero hubo un problema al sincronizar con la Cloud API.",
            )
        else:
            messages.success(
                request,
                "La colaboración fue marcada como enviada y sincronizada correctamente "
                "con la Cloud API.",
            )
    except Exception:
        messages.info(
            request,
            "La colaboración fue marcada como enviada. "
            "Si hubiera errores de sincronización, aparecerán en el panel de Bonita.",
        )

    return redirect("projects:project_detail", project_id=project.id)
