from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db.models import Q, F


class RequestType(models.TextChoices):
    ECON = "ECON", "Económica"
    MAT = "MAT", "Materiales"
    MO = "MO", "Mano de obra"
    OTRO = "OTRO", "Otro"


class RequestStatus(models.TextChoices):
    OPEN = "OPEN", "Pendiente"
    RESERVED = "RESERVED", "Reservada"
    COMPLETED = "COMPLETED", "Completada"


class CommitmentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Comprometido"
    FULFILLED = "FULFILLED", "Completado"
    CANCELLED = "CANCELLED", "Cancelado"

class ProjectStatus(models.TextChoices):
    OPEN = "OPEN", "Abierto"
    WITH_COMMITMENTS = "WITH_COMMITMENTS", "Con compromisos"
    READY = "READY", "Listo para ejecutar"
    EXECUTING = "EXECUTING", "En ejecución"
    FINISHED = "FINISHED", "Finalizado"


class Project(models.Model):
    """
    Proyecto.
    """
    
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    created_by_ong = models.CharField(max_length=200, blank=True)
    bonita_case_id = models.CharField(max_length=64, blank=True, null=True)
    monitoring_case_id = models.CharField(max_length=64, blank=True, null=True)
    has_monitoring = models.BooleanField(default=False)
    
    created_by_user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name="projects"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, choices=ProjectStatus.choices, default=ProjectStatus.OPEN)

    def __str__(self): 
        return f"{self.name} ({self.start_date} – {self.end_date})"

    class Meta:
        db_table = "projects"
        ordering = ['-created_at']


class CollaborationRequest(models.Model):
    """
    Pedido de colaboración (dinero, materiales, etc.)
    """
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="requests")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    request_type = models.CharField(max_length=10, choices=RequestType.choices)

    target_qty = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)]
    )
    reserved_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fulfilled_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    status = models.CharField(
        max_length=12, choices=RequestStatus.choices,
        default=RequestStatus.OPEN, db_index=True
    )
    needs_help = models.BooleanField(default=True)
    cloud_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'collaboration_request'
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.CheckConstraint(check=Q(reserved_qty__gte=0), name="req_reserved_nonneg"),
            models.CheckConstraint(check=Q(fulfilled_qty__gte=0), name="req_fulfilled_nonneg"),
        ]

    def __str__(self):
        return f"{self.title} [{self.get_request_type_display()}] ({self.status})"


class Commitment(models.Model):
    """
    Compromiso de colaboración.
    """
    
    request = models.ForeignKey(
        CollaborationRequest, on_delete=models.CASCADE, related_name="commitments"
    )

    actor_label = models.CharField(max_length=140, blank=True, null=True, db_index=True)

    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=12, choices=CommitmentStatus.choices,
        default=CommitmentStatus.ACTIVE, db_index=True
    )
    commitment_date = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "commitment"
        ordering = ["-commitment_date"]
        indexes = [
            models.Index(fields=["request", "status"]),
        ]

    def __str__(self):
        who = self.actor_label or "Sin actor"
        return f"Compromiso de {who} → {self.request.title} ({self.status})"


class Stage(models.Model):
    """
    Etapa del plan de trabajo de un proyecto.
    """
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="stages")
    
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['start_date', 'created_at']

    def __str__(self):
        return self.name


class Observation(models.Model):
    """
    Observación del Consejo Directivo.
    """
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="observations")
    
    observer_label = models.CharField(max_length=150, help_text="Nombre del Consejo o supervisor")
    text = models.TextField(help_text="Descripción de la observación o mejora")
    resolved = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Observación para {self.project.name}"


class FinalReport(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="final_report")

    actual_start_date = models.DateField(null=True, blank=True)
    actual_end_date = models.DateField(null=True, blank=True)
    summary = models.TextField("Resumen de resultados", blank=True)
    contributions = models.TextField("Aportes recibidos", blank=True)
    difficulties = models.TextField("Dificultades encontradas", blank=True)
    comments = models.TextField("Comentarios adicionales", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Informe final del proyecto {self.project.id}"
