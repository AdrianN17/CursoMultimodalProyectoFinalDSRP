"""Fixtures: MOCK de IA + herramientas en proceso + SQL simulado (SQLite temporal, ver sql_falso.py).

Por defecto NO se toca ninguna base real ni la red: la suite corre en segundos.
Para validar contra SQL Server / Azure SQL reales (usa la BD de .env y la recarga): RUN_INTEGRACION=1 pytest
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(Path(__file__).parent))
os.environ["PROVEEDOR_IA"] = "mock"
os.environ["MCP_TRANSPORT"] = "inproc"
os.environ["DEMO_MODE"] = "1"
# Los embeddings mock (256 dim) no deben tocar la colección real de Qdrant Cloud (1536 dim): Qdrant local y sin OTLP.
os.environ["QDRANT_URL"] = ""
os.environ["QDRANT_API_KEY"] = ""
os.environ["QDRANT_PATH"] = str(RAIZ / ".qdrant_test")
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""
# Aislar de los valores reales de .env (load_dotenv no pisa variables ya definidas).
os.environ["ANALISTA_API_KEY"] = "demo-analista"
os.environ["CASO_ID"] = "C-07"
os.environ["SEMILLA"] = "4213"

INTEGRACION = os.environ.get("RUN_INTEGRACION") == "1"


def _importar_script(nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / "scripts" / f"{nombre}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


if not INTEGRACION:
    import sql_falso

    # SQLite no tiene esquemas: sin prefijo (el código y el changelog usan nombres planos en este modo).
    os.environ["AZURE_SQL_SCHEMA"] = ""
    # Debe ocurrir antes de importar `reclamos`: db.py, el checkpointer y las tools hacen `import pyodbc`.
    sql_falso.instalar(lambda: _importar_script("aplicar_esquema")._cargar(
        RAIZ / "db" / "changelog" / "db.changelog-master.yaml"))

from reclamos import db  # noqa: E402
from reclamos.escenario import construir_escenario  # noqa: E402
from reclamos.escenario.artefactos import generar_artefactos  # noqa: E402

SEED = _importar_script("seed_db")


def pytest_configure(config):
    config.addinivalue_line("markers", "integracion: requiere SQL Server real (RUN_INTEGRACION=1)")


def pytest_collection_modifyitems(config, items):
    if INTEGRACION:
        return
    saltar = pytest.mark.skip(reason="requiere SQL Server real y otro proceso: RUN_INTEGRACION=1")
    for item in items:
        if "integracion" in item.keywords:
            item.add_marker(saltar)


@pytest.fixture(scope="session")
def servicio():
    from reclamos.orquestador.servicio import ProcesadorReclamos
    srv = ProcesadorReclamos()
    yield srv
    srv.cerrar()


@pytest.fixture()
def escenario(servicio, tmp_path):
    """Fábrica: carga un escenario en la BD y genera audio + constancia. Devuelve (esc, sesion, rutas)."""
    def _crear(tipo=None, caso_id="C-07", semilla=4213):
        esc = construir_escenario(caso_id, semilla, tipo)
        SEED.cargar(esc)
        rutas = generar_artefactos(esc, tmp_path, servicio.prov)
        sesion = servicio.iniciar_sesion(caso_id, semilla)
        return esc, sesion, rutas
    return _crear


def fila(sql, params=()):
    return db.uno(sql, params)
