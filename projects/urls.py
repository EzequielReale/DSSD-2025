from django.urls import path

from . import views_solicitante as sol
from . import views_colaboradora as col
from . import views_gerencial as ger
from . import views

urlpatterns = [
    # Compartidas entre algunos o todos los roles
    path("projects/", views.projects_list, name="projects_list"),
    path("projects/<int:project_id>/", views.project_detail, name="project_detail"),

    # ONG SOLICITANTE
    path("projects/create/", sol.project_create, name="project_create"),
    path("projects/success/", sol.project_success, name="project_success"),
    path("projects/<int:project_id>/stages/add/", sol.add_stage, name="add_stage"),
    path("observations/<int:observation_id>/resolve/",
         sol.resolve_observation, name="observation_resolve",
    ),

    # ONG COLABORADORA
    path("needs/", col.needs, name="needs"),
    # path("needs/<int:need_id>/commit", col.create_commitment, name="create_commitment"),
    # path("commitments/", col.my_commitments, name="my_commitments"),
    # rutas para aceptar/ejecutar colaboraciones

    # CONSEJO DIRECTIVO / GERENCIAL
    path(
        "projects/<int:project_id>/observations/add/",
        ger.add_observation,
        name="add_observation",
    ),
    # path("dashboard/", ger.dashboard, name="dashboard")
]
