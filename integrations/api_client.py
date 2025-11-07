import requests
import uuid
from decimal import Decimal
from django.conf import settings

API_BASE_URL = "https://dssd-cloud-api-ypdl.onrender.com/api" 
# TODO: Implementar un token JWT real. Por ahora, asumimos que la API es accesible.
API_TOKEN = getattr(settings, "CLOUD_API_TOKEN", None)

class ApiClient:
    """
    Cliente simple para interactuar con la API de Cloud.
    """
    def _get_headers(self):
        # if not API_TOKEN:
        #     raise ValueError("CLOUD_API_TOKEN no está configurado en settings.py")
        # return {'Authorization': f'Bearer {API_TOKEN}'}
        return {'Accept': 'application/json'} # Por ahora...

    def _make_request(self, method, endpoint, params=None, json=None):
        url = f"{API_BASE_URL}{endpoint}"
        try:
            r = requests.request(
                method, 
                url, 
                headers=self._get_headers(),
                params=params, 
                json=json,
                timeout=10
            )
            r.raise_for_status() # Lanza error si es 4xx o 5xx
            return r.json()
        except requests.exceptions.RequestException as e:
            # TODO: Manejar mejor los errores
            print(f"Error en API Client: {e}")
            return None # O relanzar

    # --- Requests ---
    def get_requests(self, project_ref=None, type=None, include_all=False):
        params = {}
        if project_ref:
            return self._make_request("get", f"/requests/by-project/{project_ref}/")
        
        if type: params['type'] = type
        if include_all: params['include_all'] = '1'
        return self._make_request("get", "/requests/", params=params)

    def create_request(self, project_ref: uuid.UUID, data: dict):
        payload = {
            "project_ref": str(project_ref),
            "need_ref": str(uuid.uuid4()), # UUID único para la necesidad
            "title": data.get("detalle", "Sin título")[:50],
            "description": data.get("detalle"),
            "request_type": data.get("tipo"),
            "target_qty": str(data.get("cantidad", 0)),
        }
        return self._make_request("post", "/requests/", json=payload)

    # --- Stages ---
    def get_stages(self, project_ref: uuid.UUID):
        return self._make_request("get", f"/stages/by-project/{project_ref}/")

    def create_stage(self, project_ref: uuid.UUID, data: dict):
        payload = {
            "project_ref": str(project_ref),
            "name": data.get("name"),
            "description": data.get("description"),
            "start_date": data.get("start_date").isoformat(),
            "end_date": data.get("end_date").isoformat(),
        }
        return self._make_request("post", "/stages/", json=payload)

    # --- Observations ---
    def get_observations(self, project_ref: uuid.UUID):
        return self._make_request("get", f"/observations/by-project/{project_ref}/")

    def create_observation(self, project_ref: uuid.UUID, data: dict):
        payload = {
            "project_ref": str(project_ref),
            "observer_label": data.get("observer_label", "Consejo"),
            "text": data.get("text"),
        }
        return self._make_request("post", "/observations/", json=payload)
