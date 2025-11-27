import time
from dateutil import parser
from datetime import timedelta
import statistics

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.utils import timezone
from django.conf import settings

from ProjectPlanning.decorators import require_user_passes_test

from .models import Project, Observation
from .forms import ObservationForm
from .views import is_consejo_directivo, _wants_json
from integrations.bonita_client import BonitaClient
from .services import ProjectService

service = ProjectService()

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


@require_user_passes_test(is_consejo_directivo)
def compliance_report(request):
    """
    HU7: Reporte de Cumplimiento de Plazos.
    Compara cuándo se creó la observación vs cuándo se cerró la tarea en Bonita.
    """
    template_name = "projects/reporte_cumplimiento.html"
    
    # 1. Obtenemos observaciones resueltas de la BD
    observaciones = Observation.objects.filter(is_resolved=True).select_related('project')
    reporte = []

    for obs in observaciones:
        case_id = obs.project.bonita_case_id
        if not case_id:
            continue

        # 2. Buscamos en Bonita cuándo se cerró la tarea "Resolver problemas"
        # Asumimos que la última tarea de este tipo corresponde a esta observación
        try:
            tareas_archivadas = client_directivo.get_archived_human_tasks(case_id, "Resolver problemas")
        except Exception:
            tareas_archivadas = []
        
        if tareas_archivadas:
            # Tomamos la más reciente
            tarea_bonita = tareas_archivadas[0]
            fecha_fin_bonita_str = tarea_bonita.get('archivedDate') # Bonita devuelve string
            
            if fecha_fin_bonita_str:
                # Convertimos el string de Bonita a fecha real
                fecha_fin = parser.parse(fecha_fin_bonita_str)
                fecha_inicio = obs.created_at
                
                # CÁLCULO: Tiempo real = Fecha Fin - Fecha Inicio
                tiempo_tardado = fecha_fin - fecha_inicio
                dias_tardados = tiempo_tardado.days
                
                cumple = dias_tardados <= 5
                
                reporte.append({
                    'proyecto': obs.project.name,
                    'observacion': obs.text, # Note: Observation model uses 'text' not 'description' based on models.py
                    'fecha_inicio': fecha_inicio,
                    'fecha_fin': fecha_fin,
                    'dias_tardados': dias_tardados,
                    'cumple_plazo': cumple
                })

    context = {'reporte': reporte}
    return render(request, template_name, context)

@require_user_passes_test(is_consejo_directivo)
def lifecycle_metrics(request):
    """
    HU8: Métricas de Ciclo de Vida.
    Promedio de duración desde Alta del Proyecto hasta Fin del proceso en Bonita.
    """
    template_name = "projects/metricas_ciclo_vida.html"

    projects = Project.objects.all()
    
    duraciones_por_mes = {} # Diccionario para agrupar: {'Octubre': [5, 10, 2], 'Noviembre': [1]}

    for proj in projects:
        if not proj.bonita_case_id:
            continue
            
        start_date = proj.start_date
        end_date = None
        
        # Buscamos si el caso ya terminó completamente en Bonita
        try:
            caso_archivado = client_directivo.get_archived_case(proj.bonita_case_id)
        except Exception:
            caso_archivado = None
        
        print(caso_archivado)

        if caso_archivado:
            # Si terminó, usamos la fecha de archivo del caso
            end_date = parser.parse(caso_archivado['end_date'])
        else:
            # Si no terminó, buscamos si llegó a la tarea "Ejecución del proyecto" (hito intermedio)
            try:
                tareas_ejecucion = client_directivo.get_archived_human_tasks(proj.bonita_case_id, "Ejecución del proyecto")
            except Exception:
                tareas_ejecucion = []

            print(tareas_ejecucion)

            if tareas_ejecucion:
                end_date = parser.parse(tareas_ejecucion[0]['archivedDate'])
        
        if start_date and end_date:
            # CÁLCULO: Duración = Fin - Inicio
            delta = end_date - start_date
            mes_nombre = start_date.strftime("%B") # Ej: "October"
            
            if mes_nombre not in duraciones_por_mes:
                duraciones_por_mes[mes_nombre] = []
            duraciones_por_mes[mes_nombre].append(delta.days)

    # CÁLCULO: Promedio por mes
    datos_grafico = []
    for mes, duraciones in duraciones_por_mes.items():
        promedio = statistics.mean(duraciones) if duraciones else 0
        datos_grafico.append({
            'mes': mes,
            'promedio': round(promedio, 1) # Redondeamos a 1 decimal
        })
        
    context = {'datos_grafico': datos_grafico}
    return render(request, template_name, context)

@require_user_passes_test(is_consejo_directivo)
def stalled_projects_monitor(request):
    """
    HU9: Monitor de Proyectos Detenidos.
    Alerta si una tarea está activa sin tocarse por más de 72hs.
    """
    template_name = "projects/monitor_detenidos.html"

    
    # Obtenemos proyectos activos de la BD
    proyectos_activos = Project.objects.filter(
        status__in=['OPEN', 'WITH_COMMITMENTS', 'READY', 'EXECUTING'])
    detenidos = []

    print(proyectos_activos)
    
    ahora = timezone.now()

    for proj in proyectos_activos:
        if not proj.bonita_case_id:
            continue
            
        # Consultamos las tareas pendientes en Bonita
        try:
            tareas_activas = client_directivo.get_active_tasks(proj.bonita_case_id)
        except Exception:
            tareas_activas = []
        
        print(tareas_activas)
        
        for tarea in tareas_activas:
            # La fecha de asignación viene como string, la convertimos
            assigned_date_str = tarea.get('assigned_date')
            if not assigned_date_str:
                continue # Si nadie la tomó todavía, quizás no cuenta (o usamos last_update_date)
                
            assigned_date = parser.parse(assigned_date_str)
            
            # CÁLCULO: Tiempo detenido = Ahora - Fecha Asignación
            tiempo_detenido = ahora - assigned_date
            
            if tiempo_detenido > timedelta(hours=72):
                # Recuperamos info del usuario asignado (si existe)
                usuario_nombre = "Sin asignar"
                if 'assigned_id' in tarea and tarea['assigned_id']:
                    # Nota: Bonita a veces devuelve el objeto entero en assigned_id dependiendo del expand 'd'
                    user_data = tarea.get('assigned_id')
                    if isinstance(user_data, dict):
                        usuario_nombre = f"{user_data.get('firstname', '')} {user_data.get('lastname', '')}"
                    else:
                        usuario_nombre = f"ID {user_data}"

                detenidos.append({
                    'proyecto': proj.name,
                    'tarea': tarea.get('displayName'),
                    'responsable': usuario_nombre,
                    'horas_detenido': int(tiempo_detenido.total_seconds() / 3600)
                })

    print(detenidos)
    
    context = {'proyectos_detenidos': detenidos}
    return render(request, template_name, context)
    