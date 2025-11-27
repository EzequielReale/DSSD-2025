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
    path("projects/<int:project_id>/analyze-commitment/",
        sol.analyze_commitment, name="analyze_commitment",
    ),
    path("projects/<int:project_id>/execute/", sol.execute_project, name="execute_project"),


    # ONG COLABORADORA
    path("colab/projects/", col.collab_projects, name="collab_projects"),
    path(
        "colab/projects/<int:project_id>/needs/",
        col.collab_project_needs,
        name="collab_project_needs",
    ),
    path(
        "colab/projects/<int:project_id>/needs/<int:request_id>/offer/",
        col.offer_commitment,
        name="offer_commitment",
    ),
    path(
        "projects/<int:project_id>/commitments/<int:commitment_id>/fulfill/",
        col.fulfill_commitment, name="fulfill_commitment",
    ),


    # CONSEJO DIRECTIVO / GERENCIAL
    path(
        "projects/<int:project_id>/observations/add/",
        ger.add_observation,
        name="add_observation",
    ),
    # path("dashboard/", ger.dashboard, name="dashboard")
    path('reports/compliance/',
         ger.compliance_report,
         name='compliance_report'),
    path('reports/lifecycle/',
         ger.lifecycle_metrics,
         name='lifecycle_metrics'),
    path('reports/stalled/',
         ger.stalled_projects_monitor,
         name='stalled_projects_monitor'),
]
