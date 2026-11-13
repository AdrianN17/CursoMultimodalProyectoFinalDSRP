"""Construcción del grafo LangGraph: nodos (por capa) + routers + checkpointer en Azure SQL."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from . import routers as r
from .base import Contexto
from .estado import ReclamoState
from .nodos.datos import DatosMixin
from .nodos.decision import DecisionMixin
from .nodos.entrada import EntradaMixin
from .nodos.salida import SalidaMixin


class Nodos(EntradaMixin, DatosMixin, DecisionMixin, SalidaMixin):
    def __init__(self, ctx: Contexto):
        self.ctx = ctx


def construir_grafo(ctx: Contexto, checkpointer):
    n = Nodos(ctx)
    g = StateGraph(ReclamoState)
    for nombre in ("validar_entrada", "stt", "clasificar_intencion", "verificar_otp", "vision_constancia",
                   "abrir_ticket", "consultar_maestro", "cruzar_evidencias", "evaluar_politicas",
                   "recuperar_politica", "analizar_agente", "aprobacion_humana", "ejecutar_accion",
                   "escalar_operador", "finalizar", "consultar_estado", "responder_error", "componer_respuesta",
                   "tts"):
        g.add_node(nombre, getattr(n, nombre))

    g.add_edge(START, "validar_entrada")
    g.add_conditional_edges("validar_entrada", r.r_validar)
    g.add_conditional_edges("stt", r.r_stt)
    g.add_conditional_edges("clasificar_intencion", r.r_clasificar)
    g.add_conditional_edges("verificar_otp", r.r_entrada)
    g.add_conditional_edges("vision_constancia", r.r_vision)
    g.add_conditional_edges("abrir_ticket", r.r_ticket)
    g.add_conditional_edges("consultar_maestro", r.r_siguiente("cruzar_evidencias"))
    g.add_conditional_edges("cruzar_evidencias", r.r_siguiente("evaluar_politicas"))
    g.add_conditional_edges("evaluar_politicas", r.r_siguiente("recuperar_politica"))
    g.add_conditional_edges("recuperar_politica", r.r_siguiente("analizar_agente"))
    g.add_conditional_edges("analizar_agente", r.r_decision)
    g.add_conditional_edges("aprobacion_humana", r.r_hitl)
    g.add_conditional_edges("ejecutar_accion", r.r_accion)
    for terminal in ("escalar_operador", "finalizar", "consultar_estado"):
        g.add_conditional_edges(terminal, r.r_siguiente("componer_respuesta"))
    g.add_edge("responder_error", "componer_respuesta")
    g.add_edge("componer_respuesta", "tts")
    g.add_edge("tts", END)
    return g.compile(checkpointer=checkpointer)
