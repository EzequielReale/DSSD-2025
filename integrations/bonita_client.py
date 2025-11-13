import requests
from django.conf import settings

class BonitaClient:
    """
    Cliente mínimo para:
      - autenticar
      - iniciar un proceso
      - setear variables de caso (opcional)
      - listar/asignar/ejecutar user tasks
      - eliminar en caso de error con la BD
    """

    def __init__(self, role: str = "SOLICITANTE"):
        self.base = settings.BONITA_URL.rstrip("/")
        self.user = settings.BONITA_USERS.get(role, settings.BONITA_USER_SOLICITANTE)
        self.password = settings.BONITA_PASS
        self.s = requests.Session()
        self.csrf = None

    def _ensure_csrf(self):
        if self.csrf:
            return
        r = self.s.post(
            f"{self.base}/loginservice",
            data={"username": self.user, "password": self.password, "redirect": "false"},
            timeout=15,
        )
        r.raise_for_status()
        self.csrf = r.headers.get("X-Bonita-API-Token") or self.s.cookies.get("X-Bonita-API-Token")
        if not self.csrf:
            raise RuntimeError("No se obtuvo X-Bonita-API-Token al autenticar en Bonita.")

    def _h_auth(self):
        return {"X-Bonita-API-Token": self.csrf}

    def _h_json(self):
        return {"X-Bonita-API-Token": self.csrf, "Content-Type": "application/json"}

    def get_process_id(self, name: str, version: str) -> str:
        self._ensure_csrf()
        r = self.s.get(
            f"{self.base}/API/bpm/process",
            headers=self._h_auth(),
            params={"f": [f"name={name}", f"version={version}"], "c": "1"},
            timeout=15,
        )
        r.raise_for_status()
        items = r.json()
        if not items:
            raise RuntimeError(f"No se encontró el proceso '{name}' v{version}")
        return items[0]["id"]

    def start_process(self, process_id: str) -> dict:
        self._ensure_csrf()
        r = self.s.post(
            f"{self.base}/API/bpm/process/{process_id}/instantiation",
            json={}, headers=self._h_json(), timeout=20
        )
        if r.status_code == 400:
            r = self.s.post(
                f"{self.base}/API/bpm/process/{process_id}/instantiation",
                json={"contract": {}}, headers=self._h_json(), timeout=20
            )
        r.raise_for_status()
        return r.json()

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

    def execute_task(self, task_id):
        """Completa la user task SIN contract (contract vacío)."""
        self._ensure_csrf()
        r = self.s.post(
            f"{self.base}/API/bpm/userTask/{task_id}/execution",
            json={"contract": {}}, headers=self._h_json(), timeout=20
        )
        r.raise_for_status()

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
