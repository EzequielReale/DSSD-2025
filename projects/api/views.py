# projects/api/views.py
from typing import Any, Dict
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated as IsAuth

from projects.models import Project, Need, Commitment


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")

class ProjectsListView(APIView):
    """
    GET /api/projects/
    Devuelve todos los proyectos con métricas simples de necesidades.
    """
    permission_classes = [IsAuth]

    def get(self, request):
        qs = (
            Project.objects.order_by("id")
            .annotate(
                needs_total=Count("needs_rel"),
                needs_open=Count(
                    "needs_rel",
                    filter=Q(needs_rel__needs_help=True, needs_rel__is_fulfilled=False),
                ),
                needs_fulfilled=Count("needs_rel", filter=Q(needs_rel__is_fulfilled=True)),
            )
        )
        out = []
        for p in qs:
            out.append({
                "id": p.id,
                "name": p.name,
                "start_date": p.start_date,
                "end_date": p.end_date,
                "needs_total": p.needs_total,
                "needs_open": p.needs_open,
                "needs_fulfilled": p.needs_fulfilled,
            })
        return Response(out)

class ProjectNeedsView(APIView):
    """
    GET  /api/projects/<project_id>/needs/?include_all=1&type=ECON|MAT|MO|OTRO
    POST /api/projects/<project_id>/needs/
      Body:
      {
        "type": "ECON"|"MAT"|"MO"|"OTRO",
        "description": "texto",
        "amount": 123.45,
        "needs_help": true  // opcional, default true
      }
    Por defecto GET devuelve solo las que requieren ayuda y no están cumplidas.
    """
    permission_classes = [IsAuth]

    def get(self, request, project_id: int):
        project = get_object_or_404(Project, pk=project_id)

        include_all = str(request.query_params.get("include_all", "")).lower() in ("1", "true", "yes")
        type_filter = request.query_params.get("type")

        qs = project.needs_rel.select_related("project")

        if not include_all:
            qs = qs.filter(needs_help=True, is_fulfilled=False)
        if type_filter:
            qs = qs.filter(type=type_filter)

        results = []
        for n in qs.order_by("-created_at", "id"):
            results.append({
                "id": n.id,
                "project_id": n.project_id,
                "type": n.type,
                "type_label": n.get_type_display(),
                "description": n.description,
                "amount": str(n.amount),
                "needs_help": n.needs_help,
                "is_fulfilled": n.is_fulfilled,
                "created_at": n.created_at.isoformat(),
                "updated_at": n.updated_at.isoformat(),
            })
        return Response(results)

    def post(self, request, project_id: int):
        project = get_object_or_404(Project, pk=project_id)

        data = request.data or {}
        ntype = data.get("type")
        desc = data.get("description")
        amount = _to_decimal(data.get("amount", 0))
        needs_help = bool(data.get("needs_help", True))

        if ntype not in ("ECON", "MAT", "MO", "OTRO"):
            return Response({"detail": "type inválido"}, status=status.HTTP_400_BAD_REQUEST)
        if not desc:
            return Response({"detail": "description es requerido"}, status=status.HTTP_400_BAD_REQUEST)

        n = Need.objects.create(
            project=project,
            type=ntype,
            description=desc,
            amount=amount,
            needs_help=needs_help,
            is_fulfilled=False,
        )

        return Response({
            "id": n.id,
            "project_id": n.project_id,
            "type": n.type,
            "type_label": n.get_type_display(),
            "description": n.description,
            "amount": str(n.amount),
            "needs_help": n.needs_help,
            "is_fulfilled": n.is_fulfilled,
            "created_at": n.created_at.isoformat(),
            "updated_at": n.updated_at.isoformat(),
        }, status=status.HTTP_201_CREATED)


class AllNeedsView(APIView):
    """
    GET /api/needs/
    Query params:
      - include_all=1
      - type=ECON|MAT|MO|OTRO
      - project=<id>
    """
    permission_classes = [IsAuth]

    def get(self, request, *args, **kwargs):
        include_all = str(request.query_params.get("include_all", "")).lower() in ("1", "true", "yes")
        type_filter = request.query_params.get("type")
        project_id = request.query_params.get("project")

        qs = Need.objects.select_related("project")

        if not include_all:
            qs = qs.filter(needs_help=True)
        if type_filter:
            qs = qs.filter(type=type_filter)
        if project_id:
            qs = qs.filter(project_id=project_id)

        results = []
        for n in qs.order_by("-created_at", "id"):
            results.append({
                "id": n.id,
                "project_id": n.project_id,
                "project_name": n.project.name if n.project_id else None,
                "type": n.type,
                "type_label": n.get_type_display(),
                "description": n.description,
                "amount": str(n.amount),
                "needs_help": n.needs_help,
                "is_fulfilled": n.is_fulfilled,
                "created_at": n.created_at.isoformat(),
                "updated_at": n.updated_at.isoformat(),
            })
        return Response(results)

class NeedCommitView(APIView):
    """
    POST /api/projects/<project_id>/needs/<need_id>/commit/
    Body:
    {
      "org_name": "ONG X" (opcional),
      "quantity": 5.5,
      "note": "texto" (opcional)
    }
    """
    permission_classes = [IsAuth]

    def post(self, request, project_id: int, need_id: int):
        need = get_object_or_404(Need.objects.select_related("project"), pk=need_id, project_id=project_id)

        data = request.data or {}
        org_name = (data.get("org_name") or "").strip()
        quantity = _to_decimal(data.get("quantity", 0))
        note = data.get("note") or ""

        if quantity <= 0:
            return Response({"detail": "quantity debe ser > 0"}, status=status.HTTP_400_BAD_REQUEST)

        c = Commitment.objects.create(
            need=need,
            org_name=org_name,
            quantity=quantity,
            note=note,
            is_completed=False,
        )

        # Recalcular “cumplida” si la suma de compromisos >= monto de la necesidad
        agg = Commitment.objects.filter(need=need).aggregate(total=Sum("quantity"))
        total_committed = agg["total"] or Decimal("0")
        if total_committed >= need.amount:
            need.is_fulfilled = True
            need.needs_help = False
            need.save(update_fields=["is_fulfilled", "needs_help"])

        return Response({
            "id": c.id,
            "need_id": need.id,
            "project_id": need.project_id,
            "org_name": c.org_name,
            "quantity": str(c.quantity),
            "note": c.note,
            "is_completed": c.is_completed,
            "created_at": c.created_at.isoformat(),
        }, status=status.HTTP_201_CREATED)


class CommitmentCompleteView(APIView):
    """
    PATCH /api/projects/<project_id>/needs/<need_id>/commitments/<commit_id>/complete/
    Body: { "completed": true|false }
    """
    permission_classes = [IsAuth]

    def patch(self, request, project_id: int, need_id: int, commit_id: int):
        need = get_object_or_404(Need.objects.select_related("project"), pk=need_id, project_id=project_id)
        commit = get_object_or_404(Commitment, pk=commit_id, need=need)

        completed = bool(request.data.get("completed", True))
        commit.is_completed = completed
        commit.completed_at = timezone.now() if completed else None
        commit.save(update_fields=["is_completed", "completed_at"])

        # Regla: si TODOS los compromisos están completos y la suma >= amount → necesidad cumplida
        agg = Commitment.objects.filter(need=need).aggregate(
            total=Sum("quantity"),
            all_completed=Count("id", filter=Q(is_completed=True)),
            total_count=Count("id"),
        )
        total_committed = agg["total"] or Decimal("0")
        all_completed = (agg["all_completed"] or 0) == (agg["total_count"] or 0)

        fulfilled = all_completed and total_committed >= need.amount
        need.is_fulfilled = fulfilled
        need.needs_help = not fulfilled
        need.save(update_fields=["is_fulfilled", "needs_help"])

        return Response({
            "id": commit.id,
            "need_id": need.id,
            "project_id": need.project_id,
            "org_name": commit.org_name,
            "quantity": str(commit.quantity),
            "note": commit.note,
            "is_completed": commit.is_completed,
            "completed_at": commit.completed_at.isoformat() if commit.completed_at else None,
        })

class MyCommitmentsView(APIView):
    """
    GET /api/commitments/
    Nota: como el modelo Commitment no guarda usuario,
    filtramos por org_name == request.user.username si eso te sirve como “identidad”.
    Ajustá esta regla si luego agregás un campo created_by.
    """
    permission_classes = [IsAuth]

    def get(self, request):
        username = (request.user.username or "").strip()
        qs = (Commitment.objects
              .select_related("need", "need__project")
              .order_by("-created_at", "id"))

        # Si usás org_name como identidad del usuario actual:
        if username:
            qs = qs.filter(org_name=username)

        results = []
        for c in qs:
            results.append({
                "id": c.id,
                "need_id": c.need_id,
                "project_id": c.need.project_id if c.need_id else None,
                "project_name": c.need.project.name if c.need_id else None,
                "org_name": c.org_name,
                "quantity": str(c.quantity),
                "note": c.note,
                "is_completed": c.is_completed,
                "completed_at": c.completed_at.isoformat() if c.completed_at else None,
                "created_at": c.created_at.isoformat(),
            })
        return Response(results)

class ProjectDetailView(APIView):
    """
    GET /api/projects/<project_id>/?include_all=1
    Devuelve el proyecto con su lista de necesidades (ORM).
    Por defecto, sólo las que requieren ayuda y no cumplidas.
    """
    permission_classes = [IsAuth]

    def get(self, request, project_id: int):
        p = get_object_or_404(Project, pk=project_id)
        include_all = str(request.query_params.get("include_all", "")).lower() in ("1", "true", "yes")

        qs = p.needs_rel.all()
        if not include_all:
            qs = qs.filter(needs_help=True, is_fulfilled=False)

        needs = []
        for n in qs.order_by("-created_at", "id"):
            needs.append({
                "id": n.id,
                "project_id": n.project_id,
                "type": n.type,
                "type_label": n.get_type_display(),
                "description": n.description,
                "amount": str(n.amount),
                "needs_help": n.needs_help,
                "is_fulfilled": n.is_fulfilled,
                "created_at": n.created_at.isoformat(),
                "updated_at": n.updated_at.isoformat(),
            })

        return Response({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "start_date": p.start_date,
            "end_date": p.end_date,
            "needs": needs,
        })