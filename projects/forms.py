from django import forms
from .models import Project, Stage, Observation


class ProjectModelForm(forms.ModelForm):
    """
    Formulario para crear/editar un Proyecto.
    """
    created_by_ong = forms.CharField(
        label="ONG creadora",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Nombre de la ONG"})
    )

    class Meta:
        model = Project
        fields = ["name", "description", "start_date", "end_date", "created_by_ong"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder":"Nombre del proyecto"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"placeholder":"Describa brevemente el proyecto"}),
        }


class NeedItemForm(forms.Form):
    """
    Formulario para agregar una necesidad (CollaborationRequest) a un proyecto.
    """
    NEED_CHOICES = [
        ("ECON", "Económica"),
        ("MAT",  "Materiales"),
        ("MO",   "Mano de obra"),
        ("OTRO", "Otro"),
    ]
    need_title = forms.CharField(
        label="Título",
        widget=forms.TextInput(attrs={"rows": 2,"placeholder": "Ingrese un título breve"
        }))
    need_type = forms.ChoiceField(label="Tipo de necesidad", choices=NEED_CHOICES)
    need_description = forms.CharField(
        label="Detalle",
        widget=forms.Textarea(attrs={
            "rows": 2,
            "placeholder": "Ingrese una descripción de la necesidad"
    }))
    quantity = forms.DecimalField(
        label="Cantidad / Monto", decimal_places=2, max_digits=12, required=True,
        help_text="Para ECON: monto; para otras: unidades/personas."
    )
    needs_help = forms.BooleanField(
        required=False,
        label="Requiere ayuda de la red",
        widget=forms.CheckboxInput(attrs={})
    )


class StageForm(forms.ModelForm):
    """
    Formulario para agregar o editar una etapa del plan de trabajo de un proyecto."""
    class Meta:
        model = Stage
        fields = ['name', 'description', 'start_date', 'end_date']
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ej: Cimientos"}),
            "description": forms.Textarea(attrs={"rows": 2, "placeholder": "Breve descripción de la etapa"}), 
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class ObservationForm(forms.ModelForm):
    class Meta:
        model = Observation
        fields = ['text']
        labels = {"text": ""}
        widgets = {
            "text": forms.Textarea(attrs={"rows": 3, "placeholder": "Escriba la observación o sugerencia"}),
        }