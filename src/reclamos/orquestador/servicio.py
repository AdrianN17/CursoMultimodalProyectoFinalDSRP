"""Servicio de aplicación: sesiones, ejecución del grafo (un span raíz por ejecución) y reanudación del HITL."""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

from langgraph.types import Command

from .. import db
from ..agente.agente import Agente
from ..config import get_settings
from ..escenario import construir_escenario
from ..hitl import aprobacion as hitl
from ..mcp_server.cliente import ClienteHerramientas
from ..memoria.checkpointer import crear_checkpointer
from ..observabilidad.otel import configurar, fijar_caso, metrica, trace_id_actual, trazar, volcar_metricas
from ..proveedores.interfaces import ProveedorIA, obtener_proveedor
from ..rag.retriever import RetrieverPoliticas
from ..seguridad.otp import emitir_otp, registrar_login
from .base import Contexto
from .grafo import construir_grafo
from .respuestas import texto_para

log = logging.getLogger("reclamos.servicio")


class ServicioError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(f"{codigo}: {mensaje}")
        self.codigo = codigo
        self.mensaje = mensaje


class ProcesadorReclamos:
    def __init__(self, proveedor: ProveedorIA | None = None, tools: ClienteHerramientas | None = None):
        configurar()
        self.settings = get_settings()
        self.prov = proveedor or obtener_proveedor()
        self.tools = tools or ClienteHerramientas()
        ctx = Contexto(settings=self.settings, prov=self.prov, agente=Agente(self.prov), tools=self.tools,
                       retriever=RetrieverPoliticas(self.prov))
        self.checkpointer = crear_checkpointer()
        self.grafo = construir_grafo(ctx, self.checkpointer)

    # ------------------------------------------------------------------------------------------
    def iniciar_sesion(self, caso_id: str | None = None, semilla: int | None = None,
                       cliente_id: str | None = None, canal: str = "web") -> dict[str, Any]:
        caso_id = caso_id or self.settings.caso_id
        semilla = self.settings.semilla if semilla is None else semilla
        fijar_caso(caso_id, semilla)
        params = {f["clave"]: f["valor"] for f in db.consultar("SELECT clave, valor FROM ParametroEscenario")}
        if params.get("caso_id") != caso_id or params.get("semilla") != str(semilla):
            raise ServicioError("ESCENARIO_NO_CARGADO",
                                f"La BD contiene el caso {params.get('caso_id')}/{params.get('semilla')}; ejecute "
                                f"scripts/seed_db.py --caso-id {caso_id} --semilla {semilla}")
        cliente_id = cliente_id or construir_escenario(caso_id, semilla).cliente_id
        if not db.uno("SELECT 1 AS x FROM Cliente WHERE cliente_id = ?", (cliente_id,)):
            raise ServicioError("CLIENTE_INEXISTENTE", f"No existe el cliente {cliente_id}")
        sesion_id = "SES-" + uuid.uuid4().hex[:10].upper()
        with trazar("sesion.iniciar", **{"sesion_id": sesion_id, "cliente_id": cliente_id}):
            otp = emitir_otp(cliente_id, sesion_id, caso_id, semilla, canal)
        log.info("sesión %s iniciada para %s", sesion_id, cliente_id)
        return {"sesion_id": sesion_id, "cliente_id": cliente_id, "caso_id": caso_id, "semilla": semilla, **otp}

    def _sesion(self, sesion_id: str) -> tuple[str, str, int]:
        f = db.uno("SELECT TOP 1 cliente_id FROM OtpChallenge WHERE sesion_id = ? ORDER BY creado_en", (sesion_id,))
        if not f:
            raise ServicioError("SESION_INEXISTENTE", f"No existe la sesión {sesion_id}")
        p = {x["clave"]: x["valor"] for x in db.consultar("SELECT clave, valor FROM ParametroEscenario")}
        return f["cliente_id"], p["caso_id"], int(p["semilla"])

    # ------------------------------------------------------------------------------------------
    def procesar(self, sesion_id: str, texto: str | None = None, audio_path: str | Path | None = None,
                 imagen_path: str | Path | None = None, otp: str | None = None,
                 idem_key: str | None = None) -> dict[str, Any]:
        cliente_id, caso_id, semilla = self._sesion(sesion_id)
        fijar_caso(caso_id, semilla)
        entrada = {
            "caso_id": caso_id, "semilla": semilla, "sesion_id": sesion_id, "cliente_id": cliente_id,
            "idem_key": idem_key, "texto": texto, "audio_path": str(audio_path) if audio_path else None,
            "imagen_path": str(imagen_path) if imagen_path else None, "otp_codigo": otp,
        }
        config = {"configurable": {"thread_id": sesion_id}}
        t0 = time.perf_counter()
        with trazar("reclamo.procesar", **{"sesion_id": sesion_id, "cliente_id": cliente_id,
                                           "entrada.audio": bool(audio_path), "entrada.imagen": bool(imagen_path),
                                           "entrada.texto": bool(texto)}) as sp:
            log.info("inicio de ejecución sesión=%s", sesion_id)
            self.grafo.invoke(entrada, config)
            return self._resultado(config, sp, t0, sesion_id)

    def resolver_hitl(self, aprobacion_id: str, decision: str, motivo: str, aprobador: str,
                      aprobador_rol: str = "ANALISTA") -> dict[str, Any]:
        """El humano decide (aprobar/rechazar) y el grafo se REANUDA desde el checkpoint en Azure SQL."""
        ap = hitl.resolver_aprobacion(aprobacion_id, decision, motivo, aprobador, aprobador_rol)
        return self._reanudar(ap)

    def expirar_pendientes(self) -> list[dict[str, Any]]:
        """Timeout HITL: lo vencido pasa a EXPIRADA y el flujo se reanuda con decisión segura (no actuar)."""
        return [self._reanudar(ap) for ap in hitl.expirar_vencidas()]

    def _reanudar(self, ap: dict) -> dict[str, Any]:
        t = db.uno("SELECT thread_id, caso_id, semilla FROM Ticket WHERE ticket_id = ?", (ap["ticket_id"],))
        fijar_caso(t["caso_id"], t["semilla"])
        config = {"configurable": {"thread_id": t["thread_id"]}}
        t0 = time.perf_counter()
        with trazar("reclamo.reanudar_hitl", **{"ticket_id": ap["ticket_id"],
                                                 "hitl.aprobacion_id": ap["aprobacion_id"]}) as sp:
            self.grafo.invoke(Command(resume={"aprobacion_id": ap["aprobacion_id"]}), config)
            return self._resultado(config, sp, t0, t["thread_id"])

    # ------------------------------------------------------------------------------------------
    def _resultado(self, config: dict, sp: Any, t0: float, sesion_id: str) -> dict[str, Any]:
        snap = self.grafo.get_state(config)
        v = snap.values
        pendiente = bool(snap.next and snap.interrupts)
        aprobacion_id = None
        if pendiente:
            payload = snap.interrupts[0].value
            aprobacion_id = payload["aprobacion_id"]
            texto = texto_para("PENDIENTE_APROBACION", {"ticket_id": v.get("ticket_id")})
            respuesta = {
                "caso_id": v["caso_id"], "semilla": v["semilla"], "sesion_id": sesion_id,
                "ticket_id": v.get("ticket_id"), "turno": v.get("turno"), "tipo_respuesta": "PENDIENTE_APROBACION",
                "accion_final": None, "accion_propuesta": payload["accion"], "inferencia": payload["inferencia"],
                "evidencias_usadas": (v.get("inferencia") or {}).get("evidencias_usadas"),
                "comparacion": v.get("comparacion"), "discrepancias": v.get("discrepancias") or [],
                "politicas_aplicables": payload["politicas"], "confianza": payload["confianza"],
                "requiere_hitl": True, "hitl": {"aprobacion_id": aprobacion_id, "estado": "PENDIENTE",
                                                "rol_requerido": payload["rol_requerido"], "monto": payload["monto"]},
                "explicacion": payload["explicacion"], "alertas": payload["alertas"], "texto_tts": texto,
            }
            audio = self._tts(texto, f"{v.get('ticket_id') or sesion_id}_t{v.get('turno', 0)}_pendiente")
        else:
            respuesta = v.get("respuesta")
            audio = v.get("audio_respuesta")
            if not respuesta:  # falla irrecuperable dentro del grafo: respuesta segura
                texto = texto_para("ERROR_TECNICO", {"ticket_id": v.get("ticket_id")})
                respuesta = {"caso_id": v.get("caso_id"), "semilla": v.get("semilla"), "sesion_id": sesion_id,
                             "ticket_id": v.get("ticket_id"), "tipo_respuesta": "ERROR_TECNICO", "texto_tts": texto}
                audio = audio or self._tts(texto, f"{sesion_id}_error")
        total_ms = round((time.perf_counter() - t0) * 1000, 2)
        resultado = respuesta["tipo_respuesta"]
        sp.set_attribute("reclamo.resultado", resultado)
        sp.set_attribute("reclamo.accion_final", respuesta.get("accion_final") or respuesta.get("accion_propuesta") or "")
        sp.set_attribute("reclamo.hitl_pendiente", pendiente)
        sp.set_attribute("latencia_total_ms", total_ms)
        if v.get("error"):
            sp.set_attribute("reclamo.error_nodo", v["error"]["nodo"])
        metrica("reclamos", 1, resultado=resultado)
        volcar_metricas()
        log.info("fin de ejecución: %s en %.0f ms (hitl_pendiente=%s)", resultado, total_ms, pendiente)
        return {"sesion_id": sesion_id, "ticket_id": v.get("ticket_id"), "trace_id": trace_id_actual(),
                "latencia_total_ms": total_ms, "pendiente_hitl": pendiente, "aprobacion_id": aprobacion_id,
                "respuesta": respuesta, "audio_path": audio, "error": v.get("error")}

    def _tts(self, texto: str, nombre: str) -> str | None:
        from .nodos.salida import DIR_SALIDAS
        try:
            DIR_SALIDAS.mkdir(parents=True, exist_ok=True)
            return str(self.prov.sintetizar(texto, DIR_SALIDAS / nombre))
        except Exception:
            log.exception("TTS falló; se entrega solo el texto en el JSON")
            return None

    def cerrar(self) -> None:
        self.tools.cerrar()
        volcar_metricas()
