"""Checkpointer en SQL y herramientas MCP: persistencia entre procesos, idempotencia y guardas de negocio."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from reclamos import db
from reclamos.hitl import aprobacion as hitl
from reclamos.memoria.sqlserver_saver import SqlServerSaver

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _enviar(srv, ses, rutas, **kw):
    return srv.procesar(ses["sesion_id"], audio_path=rutas["audio"], imagen_path=rutas["imagen"],
                        otp=ses["otp_demo"], **kw)


def test_checkpoint_persiste_en_sql_y_lo_lee_otra_instancia(servicio, escenario):
    esc, ses, rutas = escenario("DUPLICADA")
    res = _enviar(servicio, ses, rutas)
    assert res["pendiente_hitl"]
    otro = SqlServerSaver()  # instancia nueva = sin estado en memoria
    tup = otro.get_tuple({"configurable": {"thread_id": ses["sesion_id"]}})
    assert tup is not None
    assert tup.checkpoint["channel_values"]["ticket_id"] == res["ticket_id"]
    assert any(canal == "__interrupt__" for _, canal, _ in tup.pending_writes)
    assert db.uno("SELECT COUNT(*) AS n FROM checkpoints WHERE thread_id = ?", (ses["sesion_id"],))["n"] >= 2


def test_hitl_se_reanuda_desde_otro_proceso(servicio, escenario, tmp_path):
    """Simula 'el servidor se reinició mientras el humano pensaba': otro proceso aprueba y retoma el hilo."""
    esc, ses, rutas = escenario("DUPLICADA")
    res = _enviar(servicio, ses, rutas)
    env = {**os.environ, "PYTHONPATH": str(RAIZ / "src"), "QDRANT_PATH": str(tmp_path / "qd"),
           "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([sys.executable, str(RAIZ / "scripts" / "hitl_cli.py"), "decidir", res["aprobacion_id"],
                        "APROBADA", "ok desde otro proceso", "--aprobador", "ana", "--rol", "SUPERVISOR"],
                       env=env, capture_output=True, text=True, cwd=RAIZ, timeout=120)
    assert p.returncode == 0, p.stderr[-800:]
    t = db.uno("SELECT accion_ejecutada, estado FROM Ticket WHERE ticket_id = ?", (res["ticket_id"],))
    assert t["accion_ejecutada"] == esc.accion_esperada


# ---------------------------------------------------------------- herramientas
def test_crear_ticket_es_idempotente(servicio, escenario):
    esc, ses, _ = escenario("DUPLICADA")
    args = dict(cliente_id=ses["cliente_id"], tipo_reclamo="DUPLICADO", idem_key="K-X", caso_id=esc.caso_id,
                semilla=esc.semilla, thread_id=ses["sesion_id"])
    a = servicio.tools.llamar("crear_ticket", **args)
    b = servicio.tools.llamar("crear_ticket", **args)
    assert a["ok"] and b["ok"] and a["data"]["ticket_id"] == b["data"]["ticket_id"]
    assert db.uno("SELECT COUNT(*) AS n FROM Ticket")["n"] == 1


def test_transaccion_ajena_no_devuelve_detalle(servicio, escenario):
    esc, ses, _ = escenario("AJENA")
    r = servicio.tools.llamar("consultar_transaccion", cliente_id=ses["cliente_id"],
                              codigo_operacion=esc.tx_principal_codigo)
    assert r["ok"] and r["data"]["pertenece_al_cliente"] is False
    assert set(r["data"]) <= {"pertenece_al_cliente", "codigo_operacion"}, "no debe filtrar monto/fecha/empresa"


def test_solo_una_accion_por_ticket_aun_con_aprobacion(servicio, escenario):
    esc, ses, rutas = escenario("DUPLICADA")
    res = _enviar(servicio, ses, rutas)
    servicio.resolver_hitl(res["aprobacion_id"], "APROBADA", "ok", "ana", "SUPERVISOR")
    ap = hitl.obtener(res["aprobacion_id"])
    repetido = servicio.tools.llamar("registrar_reembolso", ticket_id=res["ticket_id"],
                                     transaccion_id=ap["transaccion_id"], aprobacion_id=res["aprobacion_id"])
    assert repetido["ok"] and repetido["data"]["ya_ejecutada"] is True  # reintento idempotente, sin duplicar
    otra = servicio.tools.llamar("anular_transaccion", ticket_id=res["ticket_id"],
                                 transaccion_id=ap["transaccion_id"], aprobacion_id=res["aprobacion_id"])
    assert not otra["ok"]  # otra acción distinta sobre el mismo ticket (P-05)
    assert db.uno("SELECT COUNT(*) AS n FROM Reembolso WHERE ticket_id = ?", (res["ticket_id"],))["n"] == 1


def test_pii_se_enmascara_en_los_logs(servicio, escenario):
    from reclamos.seguridad.sanitizar_pii import enmascarar_texto
    assert "juan.perez@banco.pe" not in enmascarar_texto("correo juan.perez@banco.pe tarjeta 4111 1111 1111 1234")
    assert "4111 1111 1111" not in enmascarar_texto("tarjeta 4111 1111 1111 1234")
