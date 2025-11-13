from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.contrib import messages

from ProjectPlanning.decorators import require_user_passes_test

from .models import Project, Observation
from .forms import ObservationForm
from .views import is_consejo_directivo, _wants_json
from integrations.bonita_client import BonitaClient

client_directivo = BonitaClient(role="DIRECTIVO")

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
            # TODO: acá más adelante disparar notificación vía Bonita / email
        except Exception as e:
            messages.error(request, f"Error al guardar la observación: {e}")
    else:
        messages.error(request, "El formulario de observación contenía errores.")

    return redirect("projects:project_detail", project_id=project_id)


# TODO: tablero gerencial con 3 consultas
# def dashboard(request):
#     ...
