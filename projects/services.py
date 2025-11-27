from .models import Project
from integrations.bonita_client import BonitaClient

class ProjectService:
    """
    Servicio que combina datos de BD local (Django) con estado de proceso (Bonita).
    """
    def __init__(self):
        self.bonita = BonitaClient()

    def get_full_project(self, project_id):
        """
        Devuelve un dict con:
        - 'local': Objeto Project de Django
        - 'needs': Lista de necesidades (desde Bonita)
        - 'commitments': Lista de compromisos (desde Bonita)
        """
        try:
            project = Project.objects.get(pk=project_id)
        except Project.DoesNotExist:
            return None

        context = {
            "local": project,
            "needs": [],
            "commitments": []
        }

        if not project.bonita_case_id:
            return context

        # --- MAGIA: Traer datos de Bonita ---
        # Asumimos que en Bonita tienes variables de proceso llamadas:
        # 'solicitudes' (List/JSON) y 'compromisos' (List/JSON)

        # Esto hay que parametrizarlo pero me chupa un huevo FUNCIONA CARAJO
        requests_data = self.bonita.get_case_variable(project.monitoring_case_id, "solicitudes")
        # commitments_data = self.bonita.get_case_variable(project.bonita_case_id, "compromisos")

        # Normalizar datos (por si es None o lista vacía)
        context["needs"] = requests_data if requests_data else []
        # context["commitments"] = commitments_data if commitments_data else []

        return context

    def get_all_pending_needs(self):
        """
        Para el Dashboard de Colaboradores.
        Recorre todos los proyectos activos y consolida las necesidades pendientes.
        """
        all_needs = []
        # Optimizacion: Solo proyectos con Case ID
        projects = Project.objects.filter(bonita_case_id__isnull=False)

        for p in projects:
            # Traemos la variable 'solicitudes' de cada caso
            reqs = self.bonita.get_case_variable(p.bonita_case_id, "solicitudes")

            if reqs and isinstance(reqs, list):
                for r in reqs:
                    # Filtramos solo las pendientes (ajusta el estado según tu JSON)
                    if r.get('estado') == 'PENDIENTE':
                        # Enriquecemos con datos del proyecto para mostrar en tabla
                        r['project_name'] = p.name
                        r['project_id'] = p.id
                        all_needs.append(r)

        return all_needs
        