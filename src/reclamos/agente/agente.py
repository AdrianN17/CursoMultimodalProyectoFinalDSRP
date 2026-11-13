"""Agente: combina evidencias (percepción + dato maestro + políticas) y PROPONE una acción estructurada.

El agente razona; NO ejecuta. La decisión final la toma el motor de reglas (politicas/motor.py) y las
acciones que mueven dinero exigen aprobación humana (HITL).
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from ..config import AGENTE_VERSION
from ..observabilidad.otel import trazar
from ..proveedores.interfaces import ProveedorIA
from .esquemas import AgenteSalida, Intencion
from .instrucciones import cargar_prompt

log = logging.getLogger("reclamos.agente")


class Agente:
    def __init__(self, proveedor: ProveedorIA):
        self.prov = proveedor

    def clasificar_intencion(self, texto: str) -> Intencion:
        """Modelo router (barato): intención, monto/código mencionados, intento de manipulación."""
        if not texto.strip():
            return Intencion()
        try:
            crudo = self.prov.chat_json("clasificar_intencion", cargar_prompt("clasificador_intencion_v1"),
                                        {"texto": texto}, modelo="router")
            return Intencion.model_validate(crudo)
        except (ValidationError, ValueError, KeyError) as exc:
            log.warning("clasificador devolvió salida inválida (%s); se usa intención OTRO", type(exc).__name__)
            return Intencion()

    def analizar(self, contexto: dict[str, Any]) -> AgenteSalida:
        """Modelo de razonamiento: salida JSON validada con Pydantic; 1 reintento; si falla, escala."""
        with trazar("agente.analizar", **{"agente.version": AGENTE_VERSION}) as sp:
            ultimo_error = ""
            for intento in (1, 2):
                try:
                    crudo = self.prov.chat_json("analizar_reclamo", cargar_prompt("agente_v1"), contexto,
                                                modelo="chat")
                    salida = AgenteSalida.model_validate(crudo)
                    sp.set_attribute("agente.intentos", intento)
                    sp.set_attribute("agente.accion_propuesta", salida.accion_propuesta)
                    sp.set_attribute("agente.confianza", salida.confianza)
                    return salida
                except (ValidationError, ValueError, KeyError) as exc:
                    ultimo_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    log.warning("salida del agente inválida (intento %s): %s", intento, ultimo_error)
            sp.set_attribute("agente.fallback", True)
            return AgenteSalida(
                inferencia="OTRO", accion_propuesta="ESCALAR_OPERADOR", confianza=0.0, requiere_hitl=False,
                explicacion=f"Salida del modelo inválida tras reintento ({ultimo_error}); se escala a operador.",
            )
