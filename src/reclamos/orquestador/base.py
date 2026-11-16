"""Contexto de ejecución (dependencias inyectadas) y decorador de nodos instrumentados."""
from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from typing import Any, Callable

from langgraph.errors import GraphInterrupt
from opentelemetry.trace import Status, StatusCode

from ..agente.agente import Agente
from ..config import Settings
from ..mcp_server.cliente import ClienteHerramientas
from ..observabilidad.otel import metrica, trazar
from ..proveedores.interfaces import ProveedorIA
from ..rag.retriever import RetrieverPoliticas

log = logging.getLogger("reclamos.nodos")


@dataclass
class Contexto:
    settings: Settings
    prov: ProveedorIA
    agente: Agente
    tools: ClienteHerramientas
    retriever: RetrieverPoliticas


class ErrorTecnico(Exception):
    """Fallo de infraestructura (BD/MCP/modelo): se degrada a respuesta segura + ticket PENDIENTE_TECNICO."""


def exigir(res: dict, nombre_tool: str, permitidos: tuple[str, ...] = ()) -> dict | None:
    """Devuelve data si la tool respondió OK; None si el error es de negocio y está en `permitidos`;
    en cualquier otro caso lanza ErrorTecnico (el nodo degrada a respuesta segura)."""
    if res.get("ok"):
        return res["data"]
    err = res.get("error", {})
    if err.get("codigo") in permitidos:
        return None
    raise ErrorTecnico(f"{nombre_tool}: {err.get('codigo')} {err.get('mensaje', '')}")


def nodo(nombre: str) -> Callable:
    """Un span por nodo + latencia + captura de errores (el grafo nunca se cae: degrada a 'error')."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def envoltura(self: Any, state: dict) -> dict:
            with trazar(f"nodo.{nombre}", **{"nodo": nombre, "ticket_id": state.get("ticket_id"),
                                             "turno": state.get("turno")}) as sp:
                try:
                    salida = fn(self, state) or {}
                    log.debug("nodo %s terminó; actualiza: %s", nombre, ", ".join(sorted(k for k in salida)) or "(nada)")
                except GraphInterrupt:
                    sp.set_attribute("hitl.interrumpido", True)
                    log.info("nodo %s: flujo interrumpido a la espera de aprobación humana", nombre)
                    raise
                except Exception as exc:
                    tipo = type(exc).__name__
                    log.error("nodo %s falló: %s: %s", nombre, tipo, str(exc)[:200], exc_info=True)
                    sp.record_exception(exc)
                    sp.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
                    sp.set_attribute("error.tipo", tipo)
                    metrica("errores", 1, nodo=nombre, tipo=tipo)
                    return {"error": {"nodo": nombre, "tipo": tipo, "mensaje": str(exc)[:300]},
                            "traza_nodos": [f"{nombre}:ERROR"]}
                salida.setdefault("traza_nodos", [nombre])
                return salida

        return envoltura

    return deco
