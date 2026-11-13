"""Nodos de SALIDA: estado/memoria, respuesta estructurada, errores y TTS."""
from __future__ import annotations

import logging
from pathlib import Path

from ...config import RAIZ
from ..base import exigir, nodo
from ..respuestas import texto_para

log = logging.getLogger("reclamos.nodos.salida")
DIR_SALIDAS = RAIZ / "datos" / "salidas"


class SalidaMixin:
    @nodo("consultar_estado")
    def consultar_estado(self, s):
        """Segunda interacción: el agente RECUERDA el ticket (checkpoint) y consulta su estado real en BD."""
        if not s.get("ticket_id"):
            return {"salida": {"tipo": "ERROR_USUARIO", "datos": {"codigo": "SIN_RECLAMO"}}}
        data = exigir(self.ctx.tools.llamar("consultar_ticket", ticket_id=s["ticket_id"]), "consultar_ticket")
        tk, rb = data["ticket"], data.get("reembolso") or {}
        return {"salida": {"tipo": "ESTADO", "datos": {
            "estado": tk["estado"], "resolucion": tk["resolucion"], "ticket_id": tk["ticket_id"],
            "fecha_estimada": rb.get("fecha_estimada") if rb.get("estado") == "PROGRAMADO" else None}}}

    @nodo("responder_error")
    def responder_error(self, s):
        if s.get("error_usuario"):
            return {"salida": {"tipo": "ERROR_USUARIO", "datos": {"codigo": s["error_usuario"]["codigo"]}}}
        if s.get("ticket_id"):  # degradación: el ticket queda registrado y pendiente por falla técnica
            try:
                self.ctx.tools.llamar("actualizar_ticket", ticket_id=s["ticket_id"], estado="PENDIENTE_TECNICO",
                                      evento="FALLA_TECNICA", actor="sistema",
                                      detalle_json='{"nodo": "%s"}' % (s.get("error") or {}).get("nodo", "?"))
            except Exception:  # el manejo de errores no debe generar más errores
                log.exception("no se pudo marcar el ticket como PENDIENTE_TECNICO")
        return {"salida": {"tipo": "ERROR_TECNICO", "datos": {"ticket_id": s.get("ticket_id")}}}

    @nodo("componer_respuesta")
    def componer_respuesta(self, s):
        sal = s["salida"]
        datos = {**sal["datos"], "ticket_id": sal["datos"].get("ticket_id") or s.get("ticket_id")}
        texto = texto_para(sal["tipo"], datos)
        inf, df = s.get("inferencia") or {}, s.get("decision_final") or {}
        propuesta = df.get("accion")
        # accion_final = lo que realmente se ejecutó: una acción monetaria sin ejecución (rechazo humano, vencida, ya hecha) = NINGUNA
        ejecutada = propuesta not in ("ANULACION", "REEMBOLSO") or sal["tipo"] in ("ANULADO", "REEMBOLSO_PROGRAMADO")
        respuesta = {
            "caso_id": s["caso_id"], "semilla": s["semilla"], "sesion_id": s["sesion_id"],
            "ticket_id": s.get("ticket_id"), "turno": s.get("turno"),
            "tipo_respuesta": sal["tipo"], "accion_propuesta": propuesta,
            "accion_final": propuesta if ejecutada else "NINGUNA", "resolucion": s.get("resolucion"),
            "inferencia": inf.get("inferencia"),
            "evidencias_usadas": inf.get("evidencias_usadas") or self._fuentes(s),
            "comparacion": s.get("comparacion") or None, "discrepancias": s.get("discrepancias") or [],
            "politicas_aplicables": df.get("politicas", []), "confianza": inf.get("confianza"),
            "requiere_hitl": bool(df.get("requiere_hitl")), "hitl": s.get("aprobacion"),
            "explicacion": inf.get("explicacion"), "alertas": df.get("alertas", []), "texto_tts": texto,
        }
        linea = (f"T{s.get('turno')}: {sal['tipo']} ticket={s.get('ticket_id')} "
                 f"op={(s.get('constancia') or {}).get('codigo_operacion', 'n/d')}")
        memoria = (s.get("memoria_resumen", "") + " | " + linea).strip(" |")[-600:]
        log.info("respuesta: %s | accion=%s", sal["tipo"], df.get("accion"))
        return {"respuesta": respuesta, "memoria_resumen": memoria}

    @staticmethod
    def _fuentes(s) -> list[str]:
        f = ["audio" if s.get("origen_relato") == "audio" else "texto"]
        if s.get("constancia"):
            f.append("imagen")
        if s.get("tx"):
            f.append("bd")
        return f

    @nodo("tts")
    def tts(self, s):
        DIR_SALIDAS.mkdir(parents=True, exist_ok=True)
        base = DIR_SALIDAS / f"{s.get('ticket_id') or s['sesion_id']}_t{s.get('turno', 0)}"
        ruta = self.ctx.prov.sintetizar(s["respuesta"]["texto_tts"], Path(base))
        return {"audio_respuesta": str(ruta)}
