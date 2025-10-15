from django import forms
from .models import Project


class ProjectModelForm(forms.ModelForm):
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
    NEED_CHOICES = [
        ("ECON", "Económica"),
        ("MAT",  "Materiales"),
        ("MO",   "Mano de obra"),
        ("OTRO", "Otro"),
    ]
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