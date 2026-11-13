"""Estado del grafo LangGraph (lo que se conserva entre nodos e interacciones vía checkpointer)."""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class ReclamoState(TypedDict, total=False):
    # --- identidad del caso / sesión (CASO_ID + SEMILLA) -------------------------------------
    caso_id: str
    semilla: int
    sesion_id: str
    cliente_id: str
    idem_key: str | None
    turno: int
    # --- entradas del turno (el servicio las reinicia en cada interacción) --------------------
    texto: str | None
    audio_path: str | None
    imagen_path: str | None
    otp_codigo: str | None
    # --- percepción -----------------------------------------------------------------------------
    transcripcion: str
    origen_relato: str
    intencion: dict[str, Any]
    constancia: dict[str, Any] | None
    imagen_error: str | None
    audio_ok: bool
    imagen_ok: bool
    hash_audio: str | None
    hash_imagen: str | None
    # --- ticket / dato maestro -------------------------------------------------------------------
    ticket_id: str | None
    ticket_creado: bool
    ticket_ya_resuelto: bool
    tx: dict[str, Any] | None
    duplicados: list[dict[str, Any]]
    parametros: dict[str, Any]
    ticket_accion_previa: bool
    # --- inferencia / decisión -----------------------------------------------------------------
    comparacion: dict[str, Any]
    discrepancias: list[dict[str, str]]
    decision: dict[str, Any]
    politicas: list[dict[str, Any]]
    inferencia: dict[str, Any] | None
    decision_final: dict[str, Any]
    # --- HITL / acción ---------------------------------------------------------------------------
    aprobacion: dict[str, Any] | None
    resultado_accion: dict[str, Any] | None
    resolucion: str | None
    # --- salida ----------------------------------------------------------------------------------
    salida: dict[str, Any]
    respuesta: dict[str, Any]
    audio_respuesta: str | None
    memoria_resumen: str
    error: dict[str, Any] | None
    error_usuario: dict[str, Any] | None
    traza_nodos: Annotated[list[str], operator.add]
