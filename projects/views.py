import json
from django.conf import settings
from django.forms import formset_factory
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods

from .forms import ProjectModelForm, NeedItemForm
from .models import Project
from integrations.bonita_client import BonitaClient


@require_http_methods(["GET", "POST"])
def project_create(request):
    NeedFormSet = formset_factory(
        NeedItemForm, extra=1, can_delete=True, min_num=1, validate_min=True
    )

    if request.method == "POST":
        if "add_need" in request.POST:
            post = request.POST.copy()
            total = int(post.get("needs-TOTAL_FORMS", "0"))
            post["needs-TOTAL_FORMS"] = str(total + 1)
            return render(
                request,
                "projects/project_form.html",
                {"form": ProjectModelForm(post),
                 "formset": NeedFormSet(post, prefix="needs"),
                 "error_msg": None},
            )

        form = ProjectModelForm(request.POST)
        formset = NeedFormSet(request.POST, prefix="needs")

        if not (form.is_valid() and formset.is_valid()):
            return render(
                request, "projects/project_form.html",
                {"form": form, "formset": formset, "error_msg": None},
            )

        # construir lista de necesidades para JSONField
        necesidades = []
        for f in formset.cleaned_data:
            if not f or f.get("DELETE"):
                continue
            t = f.get("need_type")
            det = f.get("need_description")
            cant = f.get("quantity")
            if t and det:
                necesidades.append({
                    "tipo": t,
                    "detalle": det,
                    "cantidad": float(cant) if cant is not None else None,
                })
        if not necesidades:
            return render(
                request, "projects/project_form.html",
                {"form": form, "formset": formset,
                 "error_msg": "Debe indicar al menos una necesidad."},
            )

        # ---- guardar con ModelForm ----
        project: Project = form.save(commit=False)
        project.necesidades = necesidades
        project.save()

        # ---- Bonita (no bloquea el guardado si falla) ----
        bonita_error = None
        try:
            client = BonitaClient()
            process_id = settings.BONITA_PROCESS_ID or client.get_process_id(
                settings.BONITA_PROCESS_NAME, settings.BONITA_PROCESS_VERSION
            )
            inst = client.start_process(process_id)
            case_id = inst.get("caseId") or inst.get("processInstanceId") or inst.get("id")

            # opcional: variable de orquestación
            client.set_case_var(case_id, "colaboracionesSolicitadas",
                                len(necesidades), "java.lang.Integer")

            tasks = client.find_ready_user_tasks(case_id)
            task = next((t for t in tasks if t.get("displayName") == "Crear proyecto en la app"), tasks[0])
            uid = client.get_session_user_id()
            client.assign_task(task["id"], uid)
            client.execute_task(task["id"])
        except Exception as e:
            bonita_error = f"No se pudo completar el flujo en Bonita: {e}"

        request.session["submitted"] = {
            "project_id": project.id,
            "bonita_error": bonita_error,
        }
        return redirect("projects:project_success")

    # GET
    return render(
        request,
        "projects/project_form.html",
        {"form": ProjectModelForm(), "formset": NeedFormSet(prefix="needs"), "error_msg": None},
    )


def project_success(request):
    data = request.session.get("submitted")
    if not data:
        return redirect("projects:project_create")

    project = Project.objects.filter(pk=data.get("project_id")).first()
    if not project:
        return redirect("projects:project_create")

    context = {"project": project, "bonita_error": data.get("bonita_error")}
    return render(request, "projects/project_success.html", context)