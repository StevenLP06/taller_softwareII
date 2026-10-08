"""
Taller Ingeniería de Software II - Pruebas de rendimiento con Locust
API: Laravel 9 (/api/users, /api/users/emails, /api/users/over-twenty, /api/users/bulk)

Variables de entorno opcionales:
  PAGINATED  = 1 (default) envía page/per_page; 0 llama sin paginar (API original)
  PER_PAGE   = 50  tamaño de página
  MAX_PAGE   = 1000 página máxima a consultar al azar
  SCENARIO   = load | stress | soak  (stress activa una rampa escalonada)

Ejemplos:
  locust -f locustfile.py --host=http://localhost:8000
  SCENARIO=stress locust -f locustfile.py --host=http://localhost:8000 --headless --html stress.html
"""
import os
import random
import uuid

from locust import HttpUser, LoadTestShape, between, task

PAGINATED = os.getenv("PAGINATED", "1") == "1"
PER_PAGE = int(os.getenv("PER_PAGE", "50"))
MAX_PAGE = int(os.getenv("MAX_PAGE", "1000"))
SCENARIO = os.getenv("SCENARIO", "load")


def page_params():
    """Parámetros de paginación (vacíos si la API no está paginada)."""
    if not PAGINATED:
        return {}
    return {"page": random.randint(1, MAX_PAGE), "per_page": PER_PAGE}


def fake_user():
    """Usuario único: el email con uuid evita 422 por duplicados bajo carga."""
    uid = uuid.uuid4().hex[:12]
    return {
        "name": f"Locust {uid}",
        "email": f"locust_{uid}@example.com",
        "birth_date": f"{random.randint(1970, 2005)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
    }


class ApiUser(HttpUser):
    # Tiempo de espera entre tareas: determina el RPS real (usuarios != RPS)
    wait_time = between(1, 3)

    def _get(self, path, name):
        with self.client.get(path, params=page_params(), name=name, catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"HTTP {r.status_code}")
                return
            try:
                body = r.json()
            except ValueError:
                r.failure("Respuesta no es JSON")
                return
            if "data" not in body:
                r.failure("Falta la clave 'data'")
            else:
                r.success()

    # GET predominante (pesos 5/3/2) y POST minoritario (peso 1)
    @task(5)
    def listado(self):
        self._get("/api/users", "GET /api/users")

    @task(3)
    def correos(self):
        self._get("/api/users/emails", "GET /api/users/emails")

    @task(2)
    def mayores_de_veinte(self):
        self._get("/api/users/over-twenty", "GET /api/users/over-twenty")

    @task(1)
    def alta_lote(self):
        payload = {"users": [fake_user() for _ in range(3)]}
        with self.client.post("/api/users/bulk", json=payload,
                            name="POST /api/users/bulk", catch_response=True) as r:
            # 422 (duplicados/validación) NO cuenta como éxito
            if r.status_code == 201:
                r.success()
            else:
                r.failure(f"HTTP {r.status_code}: {r.text[:100]}")


# ---- Rampa escalonada, solo para SCENARIO=stress ----
if SCENARIO == "stress":
    class StressShape(LoadTestShape):
        # (hasta segundo, usuarios, spawn_rate)  -> AJUSTAR según el hardware
        stages = [
            (60, 20, 5),
            (120, 50, 10),
            (180, 100, 20),
            (240, 200, 40),
            (300, 400, 80),
            (360, 800, 100),
        ]

        def tick(self):
            t = self.get_run_time()
            for end, users, rate in self.stages:
                if t < end:
                    return users, rate
            return None  # termina la prueba