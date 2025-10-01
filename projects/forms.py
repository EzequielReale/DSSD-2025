from django import forms
from .models import Project


class ProjectModelForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description", "start_date", "end_date"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(),
        }

    def clean(self):
        cleaned = super().clean()
        sd, ed = cleaned.get("start_date"), cleaned.get("end_date")
        if sd and ed and ed < sd:
            self.add_error("end_date", "La fecha de fin no puede ser anterior a la de inicio.")
        return cleaned


class NeedItemForm(forms.Form):
    NEED_CHOICES = [
        ("ECON", "Económica"),
        ("MAT",  "Materiales"),
        ("MO",   "Mano de obra"),
        ("OTRO", "Otro"),
    ]
    need_type = forms.ChoiceField(label="Tipo de necesidad", choices=NEED_CHOICES)
    need_description = forms.CharField(label="Detalle", widget=forms.Textarea(attrs={"rows": 2}))
    quantity = forms.DecimalField(
        label="Cantidad / Monto", decimal_places=2, max_digits=12, required=True,
        help_text="Para ECON: monto; para otras: unidades/personas."
    )
    needs_help = forms.BooleanField(
        required=False,
        label="Requiere ayuda de la red",
        widget=forms.CheckboxInput(attrs={})
    )