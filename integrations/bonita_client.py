import requests
from django.conf import settings

class BonitaClient:
    """
    Cliente para interactuar con la API REST de Bonita BPM.
    Maneja autenticación, instanciación y recuperación de variables.
    """

    def __init__(self):
        self.base = settings.BONITA_URL.rstrip("/")
        self.user = settings.BONITA_USER
        self.password = settings.BONITA_PASS
        self.s = requests.Session()
        self.csrf = None

    # ---------- auth ----------
    def _ensure_csrf(self):
        if self.csrf:
            return
        try:
            r = self.s.post(
                f"{self.base}/loginservice",
                data={"username": self.user, "password": self.password, "redirect": "false"},
                timeout=10,
            )
            r.raise_for_status()
            self.csrf = r.headers.get("X-Bonita-API-Token") or self.s.cookies.get("X-Bonita-API-Token")
        except Exception as e:
            print(f"Error de Login en Bonita: {e}")
            raise

    def _h_auth(self):
        self._ensure_csrf()
        return {"X-Bonita-API-Token": self.csrf}

    def _h_json(self):
        h = self._h_auth()
        h["Content-Type"] = "application/json"
        return h

    # ---------- procesos ----------
    def get_process_id(self, name, version):
        r = self.s.get(
            f"{self.base}/API/bpm/process",
            headers=self._h_auth(),
            params={"f": [f"name={name}", f"version={version}"], "c": 1},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        if data:
            return data[0]["id"]
        return None

    def start_process(self, process_id, variables=None):
        """
        Inicia un proceso y opcionalmente setea variables iniciales si el contrato lo permite.
        """
        url = f"{self.base}/API/bpm/process/{process_id}/instantiation"
        payload = {}
        if variables:
            # Usar la variable correcta
            payload = variables

        r = self.s.post(url, json=payload, headers=self._h_json(), timeout=15)
        r.raise_for_status()
        return r.json()  # Devuelve { "caseId": "123" }

    def start_process_with_contract(self, process_name, process_version, contract_data):
        """
        Busca el proceso e instancia un caso enviando datos al contrato.
        contract_data: Diccionario con los inputs definidos en el contrato de instanciación de Bonita.
        """
        # A. Buscar ID del proceso
        pid = self.get_process_id(process_name, process_version)
        if not pid:
            raise Exception(f"Proceso {process_name} v{process_version} no encontrado.")

        # B. Instanciar
        url = f"{self.base}/API/bpm/process/{pid}/instantiation"
        
        # Bonita espera el payload en formato: { "input_name": value, ... }
        payload = contract_data or {}
        
        resp = self.s.post(url, json=payload, headers=self._h_json(), timeout=15)
        resp.raise_for_status()
        
        return resp.json().get("caseId")

    def assign_and_execute_task(self, case_id, task_name, user_id):
        """Busca una tarea por nombre en un caso, la asigna y la ejecuta."""
        # 1. Buscar tarea
        r = self.s.get(
            f"{self.base}/API/bpm/userTask",
            headers=self._h_auth(),
            params={"f": [f"caseId={case_id}", "state=ready"], "c": 100}
        )
        tasks = r.json()
        target_task = next((t for t in tasks if t["displayName"] == task_name), None)
        
        if target_task:
            # 2. Asignar
            self.s.put(
                f"{self.base}/API/bpm/userTask/{target_task['id']}",
                json={"assigned_id": user_id},
                headers=self._h_json()
            )
            # 3. Ejecutar
            self.s.post(
                f"{self.base}/API/bpm/userTask/{target_task['id']}/execution",
                json={}, 
                headers=self._h_json()
            )
            return True
        return False

    # ---------- variables de caso ----------
    def get_case_variable(self, case_id, variable_name):
        """
        Obtiene el valor de una variable de proceso.
        Retorna el valor (que puede ser un dict/list si es JSON) o None.
        """
        # Primero intentamos buscarla como variable de caso activa
        try:
            url = f"{self.base}/API/bpm/caseVariable/{case_id}/{variable_name}"
            r = self.s.get(url, headers=self._h_auth())
            if r.status_code == 200:
                data = r.json()
                val = data.get("value")
                # Si Bonita devuelve strings para JSONs, intentamos parsear
                if data.get("type") == "java.util.List" or data.get("type") == "java.util.Map":
                     # A veces Bonita devuelve el objeto directo, a veces string.
                     return val
                return val
        except Exception:
            pass
            
        # Si falla (ej. caso archivado), podríamos buscar en archivedCaseVariable
        return self.get_archived_case_variable(case_id, variable_name)

    def get_archived_case_variable(self, case_id, variable_name):
        """Para cuando el proyecto finalizó"""
        # La lógica de búsqueda en archivos es más compleja en Bonita (API/bpm/archivedCaseVariable),
        # requiere buscar por sourceObjectId. Simplificamos por ahora.
        return []

    def set_case_var(self, case_id, name, value, type_hint: str | None = None):
        """Setea una variable de caso ya definida en el proceso."""
        self._ensure_csrf()
        payload = {"value": value}
        if type_hint:
            payload["type"] = type_hint
        r = self.s.put(
            f"{self.base}/API/bpm/caseVariable/{case_id}/{name}",
            json=payload, headers=self._h_json(), timeout=15
        )
        r.raise_for_status()
        return True

    # ---------- user/tasks ----------
    def get_session_user_id(self) -> str:
        """
        Intenta /API/system/session; si falla (500, etc.), busca por username:
        /API/identity/user?f=userName=<username>
        """
        self._ensure_csrf()
        # intento 1: system/session
        try:
            r = self.s.get(f"{self.base}/API/system/session", headers=self._h_auth(), timeout=10)
            if r.status_code == 200:
                return r.json()["user_id"]
        except Exception:
            pass  # vamos al fallback

        # intento 2 (fallback): identity por username
        r2 = self.s.get(
            f"{self.base}/API/identity/user",
            headers=self._h_auth(),
            params={"f": [f"userName={self.user}"], "c": "1"},
            timeout=10,
        )
        r2.raise_for_status()
        users = r2.json()
        if not users:
            raise RuntimeError(f"No se encontró el usuario '{self.user}' en identity.")
        return users[0]["id"]

    def find_ready_user_tasks(self, case_id):
        self._ensure_csrf()
        r = self.s.get(
            f"{self.base}/API/bpm/userTask",
            headers=self._h_auth(),
            params={"f": [f"state=ready", f"caseId={case_id}"], "c": "50"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def assign_task(self, task_id, user_id):
        self._ensure_csrf()
        r = self.s.put(
            f"{self.base}/API/bpm/userTask/{task_id}",
            json={"assigned_id": str(user_id)},
            headers=self._h_json(),
            timeout=10,
        )
        r.raise_for_status()

    def execute_task(self, case_id, task_name, user_id=None):
        # Buscar tarea pendiente
        resp = self.s.get(
            f"{self.base}/API/bpm/userTask",
            params={"f": [f"caseId={case_id}", "state=ready"], "c": 50},
            headers=self._h_auth(),
            timeout=15,
        )
        resp.raise_for_status()
        tasks = resp.json()
        target = next((t for t in tasks if t["displayName"] == task_name), None)
        
        if target:
            # Si se requiere asignar
            if user_id:
                self.s.put(
                    f"{self.base}/API/bpm/userTask/{target['id']}",
                    json={"assigned_id": user_id},
                    headers=self._h_json(),
                    timeout=10,
                )
            
            # Ejecutar (con contrato vacío si no se requieren más datos)
            self.s.post(
                f"{self.base}/API/bpm/userTask/{target['id']}/execution",
                json={},
                headers=self._h_json(),
                timeout=10,
            )
            return True
        return False

    def ensure_login(self):
        self._ensure_csrf()

    def abort_case(self, case_id: str | int):
        self._ensure_csrf()
        # Intento borrar el case "vivo"
        r = self.s.delete(f"{self.base}/API/bpm/case/{case_id}",
                          headers=self._h_auth(), timeout=10)
        if r.status_code in (200, 204):
            return
        if r.status_code == 404:
            # Puede estar archivado: busco archivedCase por sourceObjectId
            q = {"p": "0", "c": "1", "f": [f"sourceObjectId={case_id}"]}
            r2 = self.s.get(f"{self.base}/API/bpm/archivedCase",
                            headers=self._h_auth(), params=q, timeout=10)
            r2.raise_for_status()
            items = r2.json()
            if not items:
                return
            arch_id = items[0]["id"]
            r3 = self.s.delete(f"{self.base}/API/bpm/archivedCase/{arch_id}",
                               headers=self._h_auth(), timeout=10)
            if r3.status_code not in (200, 204):
                raise RuntimeError(f"No se pudo eliminar archivedCase {arch_id}: {r3.status_code} {r3.text}")
            return
        raise RuntimeError(f"No se pudo abortar/eliminar case {case_id}: {r.status_code} {r.text}")
