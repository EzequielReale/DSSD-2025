import requests
import json
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
        """Se asegura de tener una sesión válida y token CSRF."""
        if self.csrf:
            return
        try:
            resp = self.s.post(
                f"{self.base}/loginservice",
                data={"username": self.user, "password": self.password, "redirect": "false"},
                timeout=10
            )
            resp.raise_for_status()
            self.csrf = resp.headers.get("X-Bonita-API-Token") or self.s.cookies.get("X-Bonita-API-Token")
            if not self.csrf:
                raise ValueError("No se recibió X-Bonita-API-Token")
        except Exception as e:
            print(f"🔥 Error Login Bonita: {e}")
            raise

    def _headers(self):
        """Devuelve los headers estándar para peticiones JSON."""
        self._ensure_csrf()
        return {
            "X-Bonita-API-Token": self.csrf, 
            "Content-Type": "application/json"
        }

    # --- MÉTODOS LEGACY (Compatibilidad) ---
    # Mantengo estos alias para no romper tu código viejo que use _h_auth/_h_json
    def _h_auth(self): return {"X-Bonita-API-Token": self.csrf}
    def _h_json(self): return self._headers()
    def get_session_user_id(self):
        resp = self.s.get(f"{self.base}/API/system/session", headers=self._headers())
        return resp.json()["user_id"]

    # --- PROCESOS E INSTANCIACIÓN ---

    def get_process_id(self, name, version):
        """Busca el ID numérico de un proceso por nombre y versión."""
        try:
            resp = self.s.get(
                f"{self.base}/API/bpm/process",
                params={"f": [f"name={name}", f"version={version}"], "c": 1},
                headers=self._headers(),
                timeout=10
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
        """Instanciación simple (Legacy)."""
        url = f"{self.base}/API/bpm/process/{process_id}/instantiation"
        payload = variables if variables else {}
        resp = self.s.post(url, json=payload, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def start_process_with_contract(self, process_name, process_version, contract_data):
        """
        Instanciación MODERNA con Contratos.
        """
        pid = self.get_process_id(process_name, process_version)
        if not pid:
            raise Exception(f"Proceso {process_name} v{process_version} no encontrado.")

        url = f"{self.base}/API/bpm/process/{pid}/instantiation"
        resp = self.s.post(url, json=contract_data, headers=self._headers())
        
        if resp.status_code >= 400:
             raise Exception(f"Error al iniciar caso en Bonita: {resp.text}")
        
        return resp.json()["caseId"]

    # --- LECTURA DE VARIABLES (IMPORTANTE) ---

    def get_case_variable(self, case_id, var_name):
        """
        Obtiene el valor de una variable de caso activa.
        Maneja el parseo de JSON si Bonita devuelve un string serializado.
        """
        try:
            url = f"{self.base}/API/bpm/caseVariable/{case_id}/{var_name}"
            resp = self.s.get(url, headers=self._headers(), timeout=5)
            
            if resp.status_code == 404:
                print(resp.text)
                return self.get_archived_case_variable(case_id, var_name)
            
            if resp.status_code == 200:
                data = resp.json()
                val = data.get("value")
                
                # Intento de parseo JSON robusto
                if isinstance(val, str):
                    val_clean = val.strip()
                    if (val_clean.startswith("[") and val_clean.endswith("]")) or \
                       (val_clean.startswith("{") and val_clean.endswith("}")):
                        try:
                            return json.loads(val_clean)
                        except json.JSONDecodeError:
                            pass 
                return val
            return None
        except Exception as e:
            print(f"⚠️ Error leyendo variable {var_name} de caso {case_id}: {e}")
            return None

    def get_archived_case_variable(self, case_id, var_name):
        """Intenta buscar en histórico (ArchivedCaseVariable)."""
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
                        if (val_clean.startswith("[") and val_clean.endswith("]")) or \
                           (val_clean.startswith("{") and val_clean.endswith("}")):
                            try:
                                return json.loads(val_clean)
                            except:
                                pass
                    return val
            return None
        except Exception:
            return None

    # --- TAREAS ---

    def execute_bonita_task(self, case_id, task_name, user_id, contract=None):
        try:
            resp = self.s.get(
                f"{self.base}/API/bpm/userTask",
                params={"f": [f"caseId={case_id}", "state=ready"], "c": 50},
                headers=self._headers()
            )
            tasks = resp.json()
            print(f"DEBUG: Tasks found for case {case_id}: {[t['displayName'] for t in tasks]}")
            target = next((t for t in tasks if t["displayName"] == task_name), None)
            
            if target:
                tid = target['id']
                if user_id:
                    self.s.put(
                        f"{self.base}/API/bpm/userTask/{tid}",
                        json={"assigned_id": user_id},
                        headers=self._headers()
                    )
                
                payload = contract if contract else {}

                self.s.post(
                    f"{self.base}/API/bpm/userTask/{tid}/execution",
                    json=payload,
                    headers=self._headers()
                )
                return True
            return False
        except Exception as e:
            print(f"Error ejecutando tarea {task_name}: {e}")
            return False

    # --- SETTERS ---
    def set_case_var(self, case_id, name, value, type_hint=None):
        """Setea una variable de caso (Legacy)."""
        payload = {"value": value}
        if type_hint: payload["type"] = type_hint
        
        url = f"{self.base}/API/bpm/caseVariable/{case_id}/{name}"
        resp = self.s.put(url, json=payload, headers=self._headers())
        resp.raise_for_status()
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
