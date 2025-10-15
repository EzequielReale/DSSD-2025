from django.urls import path
from .views import (
    ProjectNeedsView,
    AllNeedsView,
    ProjectsListView,
    ProjectDetailView,
    NeedCommitView,
    CommitmentCompleteView,
    MyCommitmentsView
)

urlpatterns = [
    path("projects/<int:project_id>/needs/", ProjectNeedsView.as_view(), name="project-needs"),
    path("needs/", AllNeedsView.as_view(), name="all-needs"),
    path("needs/<int:need_id>/commit/", NeedCommitView.as_view(), name="need-commit"),
    path("commitments/<int:commitment_id>/complete/", CommitmentCompleteView.as_view(), name="commitment-complete"),
    path("commitments/", MyCommitmentsView.as_view(), name="my-commitments"),
    path("projects/", ProjectsListView.as_view(), name="projects-list"),
    path("projects/<int:project_id>/", ProjectDetailView.as_view(), name="project-detail"),
]
