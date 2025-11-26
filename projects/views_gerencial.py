import time

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.conf import settings

from ProjectPlanning.decorators import require_user_passes_test

from .models import Project, Observation
from .forms import ObservationForm
from .views import is_consejo_directivo, _wants_json
from integrations.bonita_client import BonitaClient

client = BonitaClient(role="DIRECTIVO")

@require_user_passes_test(is_consejo_directivo)
def start_monitoring(request, project_id):
    """
    Inicia el proceso de Monitoreo para un proyecto específico.
    """
    project = get_object_or_404(Project, pk=project_id)
    
    # Si ya tiene uno activo, no iniciamos otro
    if project.monitoring_case_id:
        messages.warning(request, "Ya existe una sesión de monitoreo activa para este proyecto.")
        return redirect('projects:project_detail', project_id=project.id)

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


@require_user_passes_test(is_consejo_directivo)
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
