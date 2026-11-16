"""HITL: resolución de aprobaciones por un humano y expiración (decisión segura por defecto = NO actuar).

El agente NO puede aprobarse a sí mismo: este módulo NO está expuesto como tool MCP.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .. import db
from ..observabilidad.otel import metrica, trazar

log = logging.getLogger("reclamos.hitl")


class HitlError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(f"{codigo}: {mensaje}")
        self.codigo = codigo
        self.mensaje = mensaje


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def obtener(aprobacion_id: str) -> dict | None:
    return db.uno("SELECT * FROM AprobacionHitl WHERE aprobacion_id = ?", (aprobacion_id,))


def listar(estado: str | None = "PENDIENTE") -> list[dict]:
    sql = ("SELECT a.aprobacion_id, a.ticket_id, a.accion_propuesta, a.transaccion_id, a.monto, a.rol_requerido, "
           "a.estado, a.solicitada_en, a.expira_en, a.resumen_json, t.thread_id FROM AprobacionHitl a "
           "JOIN Ticket t ON t.ticket_id = a.ticket_id")
    if estado:
        return db.consultar(sql + " WHERE a.estado = ? ORDER BY a.solicitada_en", (estado,))
    return db.consultar(sql + " ORDER BY a.solicitada_en")


def resolver_aprobacion(aprobacion_id: str, decision: str, motivo: str, aprobador: str, aprobador_rol: str) -> dict:
    """APROBADA/RECHAZADA por un humano. Atómico: solo pasa si sigue PENDIENTE y no venció."""
    if decision not in ("APROBADA", "RECHAZADA"):
        raise HitlError("DECISION_INVALIDA", "La decisión debe ser APROBADA o RECHAZADA")
    with trazar("hitl.decision", **{"hitl.aprobacion_id": aprobacion_id, "hitl.aprobador": aprobador,
                                    "hitl.rol": aprobador_rol}) as sp:
        ap = obtener(aprobacion_id)
        if not ap:
            log.warning("HITL: no existe la aprobación %s", aprobacion_id)
            raise HitlError("NO_EXISTE", f"No existe la aprobación {aprobacion_id}")
        log.debug("HITL %s: estado=%s rol_requerido=%s accion=%s monto=%s", aprobacion_id, ap["estado"],
                  ap["rol_requerido"], ap["accion_propuesta"], ap["monto"])
        if ap["estado"] != "PENDIENTE":
            sp.set_attribute("hitl.resultado", "YA_RESUELTA")
            log.warning("HITL %s: ya estaba %s; se ignora la decisión", aprobacion_id, ap["estado"])
            raise HitlError("YA_RESUELTA", f"La aprobación ya está {ap['estado']}")
        if ap["expira_en"] < _ahora():
            _marcar_expirada(ap)
            sp.set_attribute("hitl.resultado", "EXPIRADA")
            log.warning("HITL %s: la solicitud venció; no se ejecuta la acción", aprobacion_id)
            raise HitlError("EXPIRADA", "La solicitud venció; por seguridad no se ejecuta la acción")
        if ap["rol_requerido"] == "SUPERVISOR" and aprobador_rol != "SUPERVISOR":
            sp.set_attribute("hitl.resultado", "ROL_INSUFICIENTE")
            log.warning("HITL %s: rol %s insuficiente (se requiere SUPERVISOR)", aprobacion_id, aprobador_rol)
            raise HitlError("ROL_INSUFICIENTE", "Esta aprobación requiere rol SUPERVISOR (monto sobre el umbral)")
        n = db.ejecutar(
            "UPDATE AprobacionHitl SET estado = ?, aprobador = ?, motivo = ?, resuelta_en = SYSUTCDATETIME() "
            "WHERE aprobacion_id = ? AND estado = 'PENDIENTE'", (decision, aprobador, motivo[:300], aprobacion_id))
        if n == 0:
            raise HitlError("YA_RESUELTA", "Otra decisión se registró primero")
        _evento(ap["ticket_id"], f"HITL_{decision}", {"aprobador": aprobador, "rol": aprobador_rol,
                                                       "motivo": motivo[:300]})
        espera_ms = (_ahora() - ap["solicitada_en"]).total_seconds() * 1000
        sp.set_attribute("hitl.resultado", decision)
        sp.set_attribute("hitl.latencia_espera_ms", round(espera_ms, 1))
        sp.set_attribute("hitl.accion", ap["accion_propuesta"])
        metrica("hitl", 1, decision=decision)
        log.info("HITL %s %s por %s (%s)", aprobacion_id, decision, aprobador, aprobador_rol)
        return obtener(aprobacion_id)


def _marcar_expirada(ap: dict) -> None:
    n = db.ejecutar("UPDATE AprobacionHitl SET estado = 'EXPIRADA', resuelta_en = SYSUTCDATETIME() "
                    "WHERE aprobacion_id = ? AND estado = 'PENDIENTE'", (ap["aprobacion_id"],))
    if n:
        _evento(ap["ticket_id"], "HITL_EXPIRADA", {"aprobacion_id": ap["aprobacion_id"]})
        metrica("hitl", 1, decision="EXPIRADA")


def expirar_vencidas() -> list[dict]:
    """Barrido de timeout: toda aprobación vencida pasa a EXPIRADA (no se ejecuta nada). Devuelve las afectadas."""
    vencidas = db.consultar("SELECT * FROM AprobacionHitl WHERE estado = 'PENDIENTE' AND expira_en < ?", (_ahora(),))
    log.info("HITL: barrido de expiración, %d aprobaciones vencidas", len(vencidas))
    for ap in vencidas:
        with trazar("hitl.expiracion", **{"hitl.aprobacion_id": ap["aprobacion_id"], "hitl.resultado": "EXPIRADA"}):
            _marcar_expirada(ap)
    return vencidas


def _evento(ticket_id: str, tipo: str, detalle: dict) -> None:
    db.ejecutar("INSERT INTO TicketEvento (ticket_id, tipo, detalle_json, actor) VALUES (?, ?, ?, 'analista')",
                (ticket_id, tipo, json.dumps(detalle, ensure_ascii=False)))
