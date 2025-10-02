from django.conf import settings
from django.forms import formset_factory
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from django.db import transaction

from .forms import ProjectModelForm, NeedItemForm
from .models import Project
from integrations.bonita_client import BonitaClient


@require_http_methods(["GET", "POST"])
def project_create(request):
    NeedFormSet = formset_factory(
        NeedItemForm, extra=0, can_delete=True, min_num=1, validate_min=True
    )

    if request.method == "GET":
        return render(
            request,
            "projects/project_form.html",
            {
                "form": ProjectModelForm(),
                "formset": NeedFormSet(prefix="needs", initial=[{}]),
                "error_msg": None,
            },
        )

    form = ProjectModelForm(request.POST)
    formset = NeedFormSet(request.POST, prefix="needs")

    if not (form.is_valid() and formset.is_valid()):
        return render(
            request, "projects/project_form.html",
            {"form": form, "formset": formset, "error_msg": None},
        )

    necesidades = []
    for f in formset.cleaned_data:
        if not f or f.get("DELETE"):
            continue
        t = f.get("need_type")
        det = f.get("need_description")
        cant = f.get("quantity")
        a = f.get("needs_help")

        if t and det:
            necesidades.append({
                "tipo": t,
                "detalle": det,
                "cantidad": float(cant) if cant is not None else None,
                "needs_help": a,  # colaboración externa
            })
    if not necesidades:
        return render(
            request, "projects/project_form.html",
            {"form": form, "formset": formset,
             "error_msg": "Debe indicar al menos una necesidad."},
        )

    # ---- 1) Bonita primero (si falla, no hay DB) ----
    try:
        client = BonitaClient()
        process_id = getattr(settings, "BONITA_PROCESS_ID", None) or client.get_process_id(
            settings.BONITA_PROCESS_NAME, settings.BONITA_PROCESS_VERSION
        )
        inst = client.start_process(process_id)
        case_id = inst.get("caseId") or inst.get("processInstanceId") or inst.get("id")
        client.set_case_var(case_id, "colaboracionesSolicitadas",
                            len(necesidades), "java.lang.Integer")

        tasks = client.find_ready_user_tasks(case_id)
        if tasks:
            task = next(
                (t for t in tasks if t.get("displayName") == "Crear proyecto en la app"),
                tasks[0],
            )
            uid = client.get_session_user_id()
            client.assign_task(task["id"], uid)
            client.execute_task(task["id"])

    except Exception as e:
        return render(
            request, "projects/project_form.html",
            {"form": form, "formset": formset,
             "error_msg": f"No se pudo integrar con Bonita: Por favor, intente más tarde o contacte al administrador"},
        )

    # ---- 2) DB con transacción; si falla, compenso abortando el case ----
    try:
        with transaction.atomic():
            project: Project = form.save(commit=False)
            project.necesidades = necesidades
            if hasattr(project, "bonita_case_id"):
                project.bonita_case_id = case_id
            project.save()
    except Exception as db_err:
        try:
            client.abort_case(case_id)  # compensación
        except Exception:
            pass
        return render(
            request, "projects/project_form.html",
            {"form": form, "formset": formset,
             "error_msg": f"El proyecto no se pudo guardar: {db_err}"},
        )

    # ---- 3) éxito: Bonita + DB OK ----
    request.session["submitted"] = {"project_id": project.id, "bonita_error": None}
    return redirect("projects:project_success")


def project_success(request):
    data = request.session.get("submitted")
    if not data:
        return redirect("projects:project_create")

    project = Project.objects.filter(pk=data.get("project_id")).first()
    if not project:
        return redirect("projects:project_create")

    context = {"project": project, "bonita_error": data.get("bonita_error")}
    return render(request, "projects/project_success.html", context)
