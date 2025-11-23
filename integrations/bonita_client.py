import json
import time
import requests
from django.conf import settings


class BonitaClient:
    """
    Cliente para interactuar con la API REST de Bonita BPM.
    Maneja:
      - autenticación
      - instanciación (con o sin contrato)
      - lectura/escritura de variables de caso
      - búsqueda/ejecución de tareas humanas
    """

    def __init__(self, role: str | None = None):
        """
        Si role es None -> se usa settings.BONITA_USER (compatibilidad con código existente).
        Si role es "SOLICITANTE", "COLABORADORA" o "DIRECTIVO" -> se usan los usuarios específicos.
        """
        self.base = settings.BONITA_URL.rstrip("/")

        if role is None:
            # Compatibilidad con código existente de tu compañero
            # Asegurate de tener BONITA_USER definido en settings (por ej. igual a BONITA_USER_SOLICITANTE)
            self.user = getattr(settings, "BONITA_USER", None) or getattr(settings, "BONITA_USER_SOLICITANTE")
        else:
            role = role.upper()
            mapping = {
                "SOLICITANTE": getattr(settings, "BONITA_USER_SOLICITANTE", None),
                "COLABORADORA": getattr(settings, "BONITA_USER_COLABORADORA", None),
                "DIRECTIVO": getattr(settings, "BONITA_USER_DIRECTIVO", None),
            }
            self.user = mapping.get(role) or getattr(settings, "BONITA_USER", None)

        if not self.user:
            raise RuntimeError("No se pudo determinar el usuario de Bonita (revisar settings).")

        self.password = settings.BONITA_PASS
        self.s = requests.Session()
        self.csrf = None

    # ---------- auth ----------
    def _ensure_csrf(self):
        """Se asegura de tener una sesión válida y token CSRF."""
        if self.csrf:
            return
        try:
            resp = self.s.post(
                f"{self.base}/loginservice",
                data={"username": self.user, "password": self.password, "redirect": "false"},
                timeout=10,
            )
            resp.raise_for_status()
            self.csrf = resp.headers.get("X-Bonita-API-Token") or self.s.cookies.get("X-Bonita-API-Token")
            if not self.csrf:
                raise ValueError("No se recibió X-Bonita-API-Token")
        except Exception as e:
            print(f"🔥 Error Login Bonita ({self.user}): {e}")
            raise

    def _headers(self):
        """Devuelve headers estándar JSON + CSRF."""
        self._ensure_csrf()
        return {
            "X-Bonita-API-Token": self.csrf,
            "Content-Type": "application/json",
        }

    def _h_auth(self):
        self._ensure_csrf()
        return {"X-Bonita-API-Token": self.csrf}


    def _h_json(self):
        return self._headers()

    # ---------- sesión / usuario ----------
    def get_session_user_id(self) -> str:
        """
        Intenta /API/system/session; si falla, busca por username en /API/identity/user.
        """
        self._ensure_csrf()
        try:
            r = self.s.get(f"{self.base}/API/system/session", headers=self._h_auth(), timeout=10)
            if r.status_code == 200:
                return r.json()["user_id"]
        except Exception:
            pass

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

    # ---------- procesos e instanciación ----------
    def get_process_id(self, name, version):
        """Busca el ID numérico de un proceso por nombre y versión."""
        try:
            resp = self.s.get(
                f"{self.base}/API/bpm/process",
                params={"f": [f"name={name}", f"version={version}"], "c": 1},
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                return data[0]["id"]
            return None
        except Exception as e:
            print(f"Error buscando proceso {name}: {e}")
            return None


    def start_process(self, process_id, variables=None):
        """
        Instanciación simple (sin contrato).
        """
        url = f"{self.base}/API/bpm/process/{process_id}/instantiation"
        payload = variables if variables else {}
        resp = self.s.post(url, json=payload, headers=self._headers(), timeout=15)
        if resp.status_code >= 400:
            print("Error al instanciar proceso (start_process):", resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()  # típicamente { "caseId": "123" }


    def start_process_with_contract(self, process_name, process_version, contract_data):
        """
        Instanciación con Contract. contract_data debe cumplir con el contrato
        definido en el proceso (mismos nombres de inputs).
        """
        pid = self.get_process_id(process_name, process_version)
        if not pid:
            raise Exception(f"Proceso {process_name} v{process_version} no encontrado.")

        url = f"{self.base}/API/bpm/process/{pid}/instantiation"
        resp = self.s.post(url, json=contract_data or {}, headers=self._headers(), timeout=15)

        if resp.status_code >= 400:
            raise Exception(f"Error al iniciar caso en Bonita: {resp.status_code} {resp.text}")

        data = resp.json()
        return data.get("caseId") or data.get("id")

    # ---------- variables de caso ----------
    def get_case_variable(self, case_id, var_name):
        """
        Obtiene el valor de una variable de caso activa.
        Si el valor parece JSON (string), intenta parsearlo.
        """
        try:
            url = f"{self.base}/API/bpm/caseVariable/{case_id}/{var_name}"
            resp = self.s.get(url, headers=self._headers(), timeout=5)

            if resp.status_code == 404:
                # Puede estar archivado
                return self.get_archived_case_variable(case_id, var_name)

            if resp.status_code == 200:
                data = resp.json()
                val = data.get("value")
                print(f"[Bonita] {case_id}.{var_name} = {val!r}")

                if isinstance(val, str):
                    val_clean = val.strip()
                    if (
                            (val_clean.startswith("[") and val_clean.endswith("]"))
                            or (val_clean.startswith("{") and val_clean.endswith("}"))
                    ):
                        try:
                            return json.loads(val_clean)
                        except json.JSONDecodeError:
                            pass
                return val

            return None
        except Exception as e:
            print(f"Error leyendo variable {var_name} de caso {case_id}: {e}")
            return None


    def get_archived_case_variable(self, case_id, var_name):
        """Busca una variable en archivedCaseVariable si el caso ya terminó."""
        try:
            params = {"f": [f"caseId={case_id}", f"name={var_name}"], "p": 0, "c": 1}
            url = f"{self.base}/API/bpm/archivedCaseVariable"
            resp = self.s.get(url, params=params, headers=self._headers(), timeout=5)
            if resp.status_code == 200:
                items = resp.json()
                if items:
                    val = items[0].get("value")
                    if isinstance(val, str):
                        val_clean = val.strip()
                        if (
                                (val_clean.startswith("[") and val_clean.endswith("]"))
                                or (val_clean.startswith("{") and val_clean.endswith("}"))
                        ):
                            try:
                                return json.loads(val_clean)
                            except json.JSONDecodeError:
                                pass
                    return val
            return None
        except Exception:
            return None


    def set_case_var(self, case_id, name, value, type_hint=None):
        """Setea una variable de caso (legacy)."""
        payload = {"value": value}
        if type_hint:
            payload["type"] = type_hint

        url = f"{self.base}/API/bpm/caseVariable/{case_id}/{name}"
        resp = self.s.put(url, json=payload, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return True


    def wait_for_cloud_sync(
            self,
            case_id: int,
            ok_var: str = "cloudSyncOk",
            max_attempts: int = 10,
            delay: float = 1.0,
    ) -> tuple[bool, str | None]:
        """
        Espera a que el conector de Cloud API termine y setee cloudSyncOk / cloudSyncError.
        Devuelve (ok: bool, error_msg: str | None).
        """
        for attempt in range(max_attempts):
            try:
                ok = self.get_case_variable(case_id, ok_var)
            except RequestException:
                ok = None

            # Bonita puede devolver null o la string "null"
            if ok is None or str(ok).lower() == "null":
                time.sleep(delay)
                continue

            print(f"[Bonita] {case_id}.{ok_var} = {ok!r}")

            if str(ok).lower() == "true":
                return True, None

            return False, "Error desconocido en sincronización con Cloud API."

        return False, f"Timeout esperando respuesta del conector ({max_attempts * delay}s)"



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


    def execute_task(self, case_id, task_name, user_id=None, contract=None, timeout_sec: int = 5):
        """
        Busca, asigna y ejecuta una tarea humana por displayName.
        - Reintenta durante `timeout_sec` segundos porque la tarea puede tardar en aparecer en READY.
        - contract: dict con datos del contrato de la tarea (si tuviera).
        """
        self._ensure_csrf()
        deadline = time.time() + timeout_sec
        target = None
        tasks = []

        while time.time() < deadline and not target:
            resp = self.s.get(
                f"{self.base}/API/bpm/userTask",
                params={"f": [f"caseId={case_id}", "state=ready"], "c": 50},
                headers=self._headers(),
                timeout=15,
            )
            resp.raise_for_status()
            tasks = resp.json()
            target = next((t for t in tasks if t["displayName"] == task_name), None)
            if not target:
                time.sleep(0.5)

        if not target:
            print(f"No se encontró la tarea '{task_name}' en READY para el case {case_id}")
            return False

        tid = target["id"]

        # Asignar si hace falta
        if user_id:
            self.s.put(
                f"{self.base}/API/bpm/userTask/{tid}",
                json={"assigned_id": user_id},
                headers=self._headers(),
                timeout=10,
            )

        payload = contract if contract else {}

        # Ejecutar (dispara conectores On finish)
        resp_exec = self.s.post(
            f"{self.base}/API/bpm/userTask/{tid}/execution",
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        if resp_exec.status_code >= 400:
            print("Error al ejecutar tarea:", resp_exec.status_code, resp_exec.text)
        resp_exec.raise_for_status()

        return True

    # ---------- abortar / limpiar casos ----------
    def abort_case(self, case_id: str | int):
        self._ensure_csrf()
        r = self.s.delete(f"{self.base}/API/bpm/case/{case_id}", headers=self._h_auth(), timeout=10)
        if r.status_code in (200, 204):
            return
        if r.status_code == 404:
            # Puede estar archivado: busco archivedCase por sourceObjectId
            q = {"p": "0", "c": "1", "f": [f"sourceObjectId={case_id}"]}
            r2 = self.s.get(
                f"{self.base}/API/bpm/archivedCase",
                headers=self._h_auth(),
                params=q,
                timeout=10,
            )
            r2.raise_for_status()
            items = r2.json()
            if not items:
                return
            arch_id = items[0]["id"]
            r3 = self.s.delete(
                f"{self.base}/API/bpm/archivedCase/{arch_id}",
                headers=self._h_auth(),
                timeout=10,
            )
            if r3.status_code not in (200, 204):
                raise RuntimeError(
                    f"No se pudo eliminar archivedCase {arch_id}: {r3.status_code} {r3.text}"
                )
            return
        raise RuntimeError(f"No se pudo abortar/eliminar case {case_id}: {r.status_code} {r.text}")


    def execute_task_with_retry(self, case_id, task_name, user_id, max_retries: int = 10, delay: float = 0.3) -> bool:
        """
        Ejecuta una tarea humana de Bonita con pequeños reintentos.
        Necesario porque la tarea puede estar en 'initializing' antes de pasar a 'ready'.
        """
        for attempt in range(max_retries):
            ok = self.execute_task(case_id, task_name, user_id)
            if ok:
                return True

            time.sleep(delay)

        return False