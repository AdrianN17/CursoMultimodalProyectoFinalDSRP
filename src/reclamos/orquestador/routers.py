"""ROUTERS: funciones puras que deciden el siguiente nodo a partir del estado (reglas Python, sin LLM)."""
from __future__ import annotations

from typing import Any

State = dict[str, Any]


def _falla(s: State) -> bool:
    return bool(s.get("error") or s.get("error_usuario"))


def r_validar(s: State) -> str:
    if _falla(s):
        return "responder_error"
    return "stt" if s.get("audio_ok") else "clasificar_intencion"


def r_stt(s: State) -> str:
    return "responder_error" if _falla(s) else "clasificar_intencion"


def r_clasificar(s: State) -> str:
    """Tras clasificar la intención: ¿consulta de estado (memoria) o reclamo nuevo? ¿hay imagen que analizar?"""
    if _falla(s):
        return "responder_error"
    if (s.get("intencion") or {}).get("intencion") == "CONSULTA_ESTADO":
        return "consultar_estado"
    return "vision_constancia" if s.get("imagen_ok") else "abrir_ticket"


def r_vision(s: State) -> str:
    return "responder_error" if _falla(s) else "abrir_ticket"


def r_ticket(s: State) -> str:
    if _falla(s):
        return "responder_error"
    return "consultar_estado" if s.get("ticket_ya_resuelto") else "consultar_maestro"  # idempotencia


def r_siguiente(destino: str):
    def _r(s: State) -> str:
        return "responder_error" if _falla(s) else destino
    return _r


def r_decision(s: State) -> str:
    """Router de decisión: ruta según la decisión FINAL (motor + agente)."""
    if _falla(s):
        return "responder_error"
    accion = s["decision_final"]["accion"]
    if accion in ("ANULACION", "REEMBOLSO"):
        return "aprobacion_humana"
    if accion == "ESCALAR_OPERADOR":
        return "escalar_operador"
    return "finalizar"  # RECHAZAR | PEDIR_INFO | NO_DISPONIBLE_MONEDA


def r_hitl(s: State) -> str:
    """Tras la decisión humana: aprobada -> actuar; expirada -> escalar (default seguro); rechazada -> cerrar."""
    if _falla(s):
        return "responder_error"
    estado = (s.get("aprobacion") or {}).get("estado")
    if estado == "APROBADA":
        return "ejecutar_accion"
    return "escalar_operador" if estado in ("EXPIRADA", "PENDIENTE") else "finalizar"


def r_accion(s: State) -> str:
    if _falla(s):
        return "responder_error"
    return "escalar_operador" if s["decision_final"]["accion"] == "ESCALAR_OPERADOR" else "finalizar"
