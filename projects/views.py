import json
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

@login_required
@user_passes_test(is_ong_solicitante)
@require_http_methods(["GET", "POST"])
def project_create(request):
    NeedFormSet = formset_factory(NeedItemForm, extra=0, min_num=1)
    
    if request.method == 'POST':
        form = ProjectModelForm(request.POST)
        formset = NeedFormSet(request.POST, prefix="needs")
        
        if form.is_valid() and formset.is_valid():
            try:
                # 1. Guardar Proyecto Local (Postgres)
                project = form.save(commit=False)
                if request.user.is_authenticated:
                    project.created_by_user = request.user
                project.save()
                
                # 2. Preparar JSON para Bonita
                # Convertimos el formset en una lista de diccionarios pura
                lista_solicitudes = []
                for f in formset.cleaned_data:
                    if f and not f.get("DELETE"):
                        lista_solicitudes.append({
                            "tipo": f.get("need_type"),
                            "descripcion": f.get("need_description"),
                            "cantidad": float(f.get("quantity")), # Bonita prefiere floats/doubles
                            "ayuda": bool(f.get("needs_help")),
                            "estado": "PENDIENTE"
                        })

                # 3. Iniciar Caso en Bonita con Contrato
                # ASUMIMOS: Tu proceso tiene un contrato de instanciación con inputs:
                # - idProyectoInput (long/integer)
                # - solicitudesInput (List<Solicitud>)
                
                contract_payload = {
                    "idProyectoInput": project.id,
                    "solicitudesInput": lista_solicitudes 
                }
                
                bonita = service.bonita # Accedemos al cliente dentro del servicio
                case_id = bonita.start_process_with_contract(
                    settings.BONITA_PROCESS_NAME, 
                    settings.BONITA_PROCESS_VERSION,
                    contract_payload
                )

                # 4. Guardar referencia
                project.bonita_case_id = case_id
                project.save()
                
                # 5. (Opcional) Ejecutar la primera tarea humana si es automática
                # bonita.execute_task(case_id, "Crear proyecto en la app", bonita.get_session_user_id())

                return redirect('projects:project_success')

            except Exception as e:
                messages.error(request, f"Error de integración: {str(e)}")
    
    else:
        form = ProjectModelForm()
        formset = NeedFormSet(prefix="needs")
        
    return render(request, "projects/project_form.html", {
        "form": form, "formset": formset
    })


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
    return render(request, "projects/projects.html", {"projects": projects_list})

@login_required
def project_detail(request, project_id):
    """
    Detalle completo.
    Usa el servicio para mezclar datos locales con datos de Bonita.
    """
    data = service.get_full_project(project_id)
    
    if not data:
        messages.error(request, "Proyecto no encontrado")
        return redirect('projects:projects_list')

    return render(request, "projects/project_detail.html", {
        "project": data['local'],
        "requests": data['requests'],       # Viene de Bonita
        "commitments": data['commitments'], # Viene de Bonita
        "stages": data['local'].stages.all(),
        "observations": data['local'].observations.all(),
        # Forms para modales/acciones
        "stage_form": StageForm(),
        "observation_form": ObservationForm()
    })

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
    
    if form.is_valid():
        try:
            observation = form.save(commit=False)
            observation.project = project
            observation.save()
            messages.success(request, "Observación agregada correctamente.")
        except Exception as e:
            messages.error(request, f"Error al guardar la observación: {e}")
    else:
        messages.error(request, "El formulario de observación contenía errores.")

    return redirect("projects:project_detail", project_id=project_id)
    