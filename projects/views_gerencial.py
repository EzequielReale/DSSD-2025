import time
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.contrib import messages

from ProjectPlanning.decorators import require_user_passes_test

from .models import Project, Observation
from .forms import ObservationForm
from .views import is_consejo_directivo, _wants_json
from integrations.bonita_client import BonitaClient
from .services import ProjectService

client_directivo = BonitaClient(role="DIRECTIVO")

service = ProjectService()


@require_user_passes_test(is_consejo_directivo)
@require_http_methods(["POST"])
def add_observation(request, project_id: int):
    """
    Usuario gerencial agrega una observación a un proyecto.
    """
    project = get_object_or_404(Project, pk=project_id)
    form = ObservationForm(request.POST)

    if form.is_valid():
        try:
            observation = form.save(commit=False)
            observation.project = project
            observation.observer_label = request.user.get_full_name()
            observation.save()
            messages.success(request, "Observación agregada correctamente.")
        except Exception as e:
            messages.error(request, f"Error al guardar la observación: {e}")
    else:
        messages.error(request, "El formulario de observación contenía errores.")

    return redirect("projects:project_detail", project_id=project_id)


@require_user_passes_test(is_consejo_directivo)
@require_http_methods(["POST"])
def start_monitoring(request, project_id: int):
    """
    Consejo Directivo inicia el proceso 'Monitoreo' asociado a un proyecto.
    Auto-ejecuta la tarea 'Revisión de proyectos'.
    """
    project = get_object_or_404(Project, pk=project_id)

    if project.monitoring_case_id:
        messages.warning(
            request,
            "Ya existe una sesión de monitoreo activa para este proyecto."
        )
        return redirect("projects:project_detail", project_id=project.id)

    client = client_directivo

    try:
        instantiation_contract = {
            "idProyectoInput": project.id,
        }

        case_id = client.start_process_with_contract(
            "Monitoreo",
            settings.BONITA_PROCESS_VERSION,
            instantiation_contract,
        )

        # Guardamos el case de monitoreo
        project.monitoring_case_id = case_id
        project.save()

        task_contract = {
            "idProyectoInput": project.id,
            "aprobadoInput": True,
        }

        uid = client.get_session_user_id()

        # Intentamos hasta que la tarea aparezca
        max_retries = 12
        for attempt in range(max_retries):
            ok = client.execute_task(
                case_id=case_id,
                task_name="Revisión de proyectos",
                user_id=uid,
                contract=task_contract
            )
            if ok:
                break
            time.sleep(0.5)

        if ok:
            messages.success(
                request,
                "Monitoreo iniciado y tarea 'Revisión de proyectos' completada correctamente."
            )
        else:
            messages.warning(
                request,
                "El proceso inició, pero la tarea 'Revisión de proyectos' no apareció a tiempo."
            )

    except Exception as e:
        messages.error(request, f"Error al iniciar monitoreo: {e}")

    return redirect("projects:project_detail", project_id=project.id)
