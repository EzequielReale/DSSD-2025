from django.urls import path

from . import views_solicitante as sol
from . import views_colaboradora as col
from . import views_gerencial as ger
from . import views

urlpatterns = [
    # Compartidas entre algunos o todos los roles
    path(   
        "projects/",
        views.projects_list,
        name="projects_list",
    ),
    path(
        "projects/<int:project_id>/",
        views.project_detail,
        name="project_detail",
    ),

    # ONG SOLICITANTE
    path(
        "projects/create/",
        sol.project_create,
        name="project_create",
    ),
    path(
        "projects/success/",
        sol.project_success,
        name="project_success",
    ),
    path(
        "projects/<int:project_id>/stages/add/",
        sol.add_stage,
        name="add_stage",
    ),
    path(
        "projects/<int:project_id>/fix_observation/<int:observation_id>/",
        sol.fix_observation,
        name="fix_observation",
    ),
    path(
        "projects/<int:project_id>/analyze-commitment/",
        sol.analyze_commitment,
        name="analyze_commitment",
    ),
    path(
        "projects/<int:project_id>/execute/",
        sol.execute_project,
        name="execute_project",
    ),
    path(
        "projects/<int:project_id>/final-report/",
        sol.final_report,
        name="final_report",
    ),

    # ONG COLABORADORA
    path(
        "colab/projects/",
        col.collab_projects,
        name="collab_projects",
    ),
    path(
        "colab/projects/<int:project_id>/needs/",
        col.collab_project_needs,
        name="collab_project_needs",
    ),
    path(
        "colab/projects/<int:project_id>/needs/<int:need_id>/offer/",
        col.offer_commitment,
        name="offer_commitment",
    ),
    path(
        "colab/commitments/",
        col.my_commitments,
        name="my_commitments",
    ),
    path(
        "projects/<int:project_id>/commitments/<int:commitment_id>/fulfill/",
        col.fulfill_commitment, name="fulfill_commitment",
    ),


    # CONSEJO DIRECTIVO / GERENCIAL
    path(
        "projects/<int:project_id>/start_monitoring/",
        ger.start_monitoring,
        name="start_monitoring",
    ),
    path(
        "projects/<int:project_id>/observations/add/",
        ger.add_observation,
        name="add_observation",
    ),
    path(
        'reports/compliance/',
        ger.compliance_report,
        name='compliance_report',
    ),
    path(   
        'reports/lifecycle/',
        ger.lifecycle_metrics,
        name='lifecycle_metrics',
    ),
    path(
        'reports/stalled/',
        ger.stalled_projects_monitor,
        name='stalled_projects_monitor',
    ),
]
