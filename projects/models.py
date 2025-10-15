from django.db import models

class Project(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    created_by_ong = models.CharField(max_length=200, blank=True)
    bonita_case_id = models.CharField(max_length=64, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self): return f"{self.name} ({self.start_date} – {self.end_date})"

    class Meta:
        db_table = "projects"

NEED_TYPE_CHOICES = [
    ("ECON", "Económica"),
    ("MAT", "Materiales"),
    ("MO", "Mano de obra"),
    ("OTRO", "Otro"),
]

class Need(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="needs_rel")
    type = models.CharField(max_length=10, choices=NEED_TYPE_CHOICES)
    description = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    needs_help = models.BooleanField(default=True)
    is_fulfilled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["project"]),
            models.Index(fields=["needs_help", "is_fulfilled"]),
        ]

    def __str__(self):
        return f"[{self.project_id}] {self.type}: {self.description[:30]}"


class Commitment(models.Model):
    need = models.ForeignKey(Need, on_delete=models.CASCADE, related_name="commitments")
    org_name = models.CharField(max_length=200, verbose_name="ONG que colabora")
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.TextField(blank=True)

    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["need"])]

    def __str__(self):
        return f"{self.org_name} -> Need {self.need_id} ({self.quantity})"

class Notification(models.Model):
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"🔔 {self.title}"