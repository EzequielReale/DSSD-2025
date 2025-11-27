import time
from zoneinfo import ZoneInfo
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
    if project.has_monitoring:
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
            success = client.execute_task(
                case_id,
                "Revisión de proyectos",
                client.get_session_user_id(),
                payload
            )
            
            if success:
                # Creamos la observación placeholder para guardar el case_id
                Observation.objects.create(
                    project=project,
                    monitoring_case_id=case_id,
                    observer_label=request.user.username,
                    text="" # Se llenará en add_observation
                )
                project.has_monitoring = True
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
    
    # Buscamos la observación existente (creada en start_monitoring)
    observation = Observation.objects.filter(project=project).first()
    
    if not observation:
        messages.error(request, "Debe iniciar el monitoreo antes de agregar observaciones.")
        return redirect("projects:project_detail", project_id=project_id)
    
    form = ObservationForm(request.POST, instance=observation)
    
    if form.is_valid():
        try:
            observation = form.save(commit=False)
            observation.observer_label = f"{request.user.username}"
            observation.save()
            
            success = client.execute_task(
                    case_id=observation.monitoring_case_id,
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
def compliance_report(request):
    """
    Reporte de Cumplimiento de Plazos.
    Compara cuándo se creó la observación vs cuándo se cerró la tarea en Bonita.
    """
    # 1. Obtenemos observaciones resueltas de la BD
    observaciones = Observation.objects.filter(resolved=True).select_related('project')
    reporte = []

    print(observaciones)

    for obs in observaciones:
        # La tarea "Resolver problemas" pertenece al proceso de Monitoreo
        case_id = obs.monitoring_case_id
        if not case_id:
            continue

        # 2. Buscamos en Bonita cuándo se cerró la tarea "Resolver problemas"
        # Asumimos que la última tarea de este tipo corresponde a esta observación
        try:
            tareas_archivadas = client.get_archived_human_tasks(case_id, "Resolver problemas")
        except Exception:
            print(f"Error al obtener tareas archivadas para el caso {case_id}")
            tareas_archivadas = []
        
        print(tareas_archivadas)

        if tareas_archivadas:
            # Buscamos la primera tarea que se haya completado DESPUÉS de que se creó la observación
            tarea_bonita = None
            for tarea in tareas_archivadas:
                fecha_fin_str = tarea.get('archivedDate')
                if not fecha_fin_str:
                    continue
                    
                fecha_fin = parser.parse(fecha_fin_str)
                if timezone.is_naive(fecha_fin):
                    fecha_fin = timezone.make_aware(fecha_fin)
                
                tarea_bonita = tarea
            
            if tarea_bonita:
                fecha_fin_bonita_str = tarea_bonita.get('archivedDate')
                # Convertimos el string de Bonita a fecha real (ya lo hicimos arriba, pero para mantener estructura)
                fecha_fin = parser.parse(fecha_fin_bonita_str)
                if timezone.is_naive(fecha_fin):
                    fecha_fin = timezone.make_aware(fecha_fin)
                    
                fecha_inicio = obs.created_at
                
                # CÁLCULO: Tiempo real = Fecha Fin - Fecha Inicio
                tiempo_tardado = fecha_fin - fecha_inicio
                dias_tardados = tiempo_tardado.days
                
                # Si tardó menos de un día (0 días), mostramos 0, no -1
                if dias_tardados < 0:
                     dias_tardados = 0

                print(dias_tardados)
                
                cumple = dias_tardados < 5
                
                reporte.append({
                    'proyecto': obs.project.name,
                    'observacion': obs.text,
                    'fecha_inicio': fecha_inicio,
                    'fecha_fin': fecha_fin,
                    'dias_tardados': dias_tardados,
                    'cumple_plazo': cumple
                })

    context = {'reporte': reporte}
    print(reporte)
    return render(request, "projects/reporte_cumplimiento.html", context)

@require_user_passes_test(is_consejo_directivo)
def lifecycle_metrics(request):
    """
    Métricas de Ciclo de Vida.
    Promedio de duración desde Alta del Proyecto hasta Fin del proceso en Bonita.
    """
    projects = Project.objects.all()
    
    duraciones_por_mes = {} # Diccionario para agrupar: {'Octubre': [5, 10, 2], 'Noviembre': [1]}

    for proj in projects:
        if not proj.bonita_case_id:
            continue
            
        start_date = proj.start_date
        end_date = None
        
        # Buscamos si el caso ya terminó completamente en Bonita
        try:
            caso_archivado = client.get_archived_case(proj.bonita_case_id)
        except Exception as e:
            print(f"Error getting archived case for project {proj.name} (Case ID: {proj.bonita_case_id}): {e}")
            caso_archivado = None
        
        print(caso_archivado)

        if caso_archivado and caso_archivado.get('end_date'):
            # Si terminó, usamos la fecha de archivo del caso
            end_date = parser.parse(caso_archivado['end_date'])
        else:
            # Si no terminó, buscamos si llegó a la tarea "Ejecución del proyecto" (hito intermedio)
            try:
                tareas_ejecucion = client.get_archived_human_tasks(proj.bonita_case_id, "Ejecución del proyecto")
            except Exception as e:
                print(f"Error getting archived tasks: {e}")
                tareas_ejecucion = []

            print(tareas_ejecucion)

            if tareas_ejecucion:
                end_date = parser.parse(tareas_ejecucion[0]['archivedDate'])
        
        if start_date and end_date:
            # CÁLCULO: Duración = Fin - Inicio
            # Convertimos end_date a date para poder restar con start_date (que es date)
            if hasattr(end_date, 'date'):
                end_date = end_date.date()
                
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
    return render(request, "projects/metricas_ciclo_vida.html", context)

@require_user_passes_test(is_consejo_directivo)
def stalled_projects_monitor(request):
    """
    Monitor de Proyectos Detenidos.
    Alerta si una tarea está activa sin tocarse por más de 72hs.
    """
    # Obtenemos proyectos activos de la BD
    proyectos_activos = Project.objects.filter(
        status__in=['OPEN', 'WITH_COMMITMENTS', 'READY', 'EXECUTING'])
    detenidos = []

    print(proyectos_activos)
    bsas_tz = ZoneInfo('America/Argentina/Buenos_Aires')
    ahora = timezone.now()

    for proj in proyectos_activos:
        if not proj.bonita_case_id:
            continue
            
        # Consultamos las tareas pendientes en Bonita
        try:
            tareas_activas = client.get_active_tasks(proj.bonita_case_id)
        except Exception as e:
            print(f"Error al obtener tareas activas para proyecto {proj.name} (Case ID: {proj.bonita_case_id}): {e}")
            tareas_activas = []
        
        print(tareas_activas)
        
        for tarea in tareas_activas:
            # La fecha de asignación viene como string, la convertimos
            # Si no está asignada, usamos la fecha en que llegó al estado (reached_state_date)
            date_str = tarea.get('assigned_date') or tarea.get('reached_state_date')
            
            if not date_str:
                continue
                
            reference_date = parser.parse(date_str)
            
            # Asumimos que Bonita devuelve hora local de Argentina (UTC-3) pero naive
            if timezone.is_naive(reference_date):
                reference_date = reference_date.replace(tzinfo=bsas_tz)
            
            # CÁLCULO: Tiempo detenido = Ahora - Fecha Referencia
            tiempo_detenido = ahora - reference_date
            
            if tiempo_detenido > timedelta(seconds=3):
                # Recuperamos info del usuario asignado (si existe)
                usuario_nombre = "Sin asignar"
                if 'assigned_id' in tarea and tarea['assigned_id']:
                    # Nota: Bonita a veces devuelve el objeto entero en assigned_id dependiendo del expand 'd'
                    user_data = tarea.get('assigned_id')
                    if isinstance(user_data, dict):
                        usuario_nombre = f"{user_data.get('firstname', '')} {user_data.get('lastname', '')}"
                    else:
                        usuario_nombre = f"ID {user_data}"
                elif 'actorId' in tarea:
                    # Si no está asignada, buscamos el Rol (Actor)
                    print(f"Buscando actor {tarea['actorId']}...")
                    actor = client.get_actor(tarea['actorId'])
                    print(f"Actor encontrado: {actor}")
                    if actor:
                        usuario_nombre = actor.get('displayName') or actor.get('name')

                detenidos.append({
                    'proyecto': proj.name,
                    'tarea': tarea.get('displayName'),
                    'responsable': usuario_nombre,
                    'horas_detenido': int(tiempo_detenido.total_seconds() / 3600)
                })

    print(detenidos)
    
    context = {'proyectos_detenidos': detenidos}
    return render(request, "projects/monitor_detenidos.html", context)
    