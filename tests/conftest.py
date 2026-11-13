"""Fixtures: MOCK + herramientas en proceso + SQL Server local (las mismas tablas que Azure SQL).

ATENCIÓN: las pruebas recargan los datos de negocio de la BD configurada en .env (usar una BD de desarrollo).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
os.environ["PROVEEDOR_IA"] = "mock"
os.environ["MCP_TRANSPORT"] = "inproc"
os.environ["DEMO_MODE"] = "1"

from reclamos import db  # noqa: E402
from reclamos.escenario import construir_escenario  # noqa: E402
from reclamos.escenario.artefactos import generar_artefactos  # noqa: E402


def _cargar_seed():
    spec = importlib.util.spec_from_file_location("seed_db", RAIZ / "scripts" / "seed_db.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SEED = _cargar_seed()


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
