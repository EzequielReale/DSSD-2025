import uuid
from django.db import models

class Project(models.Model):
    project_uuid = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
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

# Este supongo que lo sacamos al choto
class Notification(models.Model):
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"🔔 {self.title}"