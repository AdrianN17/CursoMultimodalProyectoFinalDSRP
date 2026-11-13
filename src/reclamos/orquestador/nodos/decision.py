"""Nodos de DECISIÓN, CONTROL (HITL) y ACCIÓN."""
from __future__ import annotations

import json
import logging

from langgraph.types import interrupt

from ...hitl import aprobacion as hitl
from ..base import exigir, nodo

log = logging.getLogger("reclamos.nodos.decision")


class DecisionMixin:
    @nodo("aprobacion_humana")
    def aprobacion_humana(self, s):
        """HITL: crea (o recupera) la solicitud y DETIENE el flujo con interrupt() hasta que un humano decida.

        Al reanudar el nodo se re-ejecuta: por eso solicitar_aprobacion es idempotente y la decisión se lee de
        la BD (dato maestro), no del valor de reanudación.
        """
        d, inf = s["decision_final"], s.get("inferencia") or {}
        resumen = {
            "ticket_id": s["ticket_id"], "accion": d["accion"], "monto": d["monto"],
            "transaccion_id": d["transaccion_objetivo_id"], "rol_requerido": d["rol_requerido"],
            "inferencia": inf.get("inferencia"), "confianza": inf.get("confianza"),
            "explicacion": inf.get("explicacion"), "politicas": d["politicas"], "alertas": d.get("alertas", []),
            "comparacion": s.get("comparacion"),
        }
        ap = exigir(self.ctx.tools.llamar(
            "solicitar_aprobacion", ticket_id=s["ticket_id"], accion=d["accion"],
            transaccion_id=d["transaccion_objetivo_id"], monto=d["monto"], rol_requerido=d["rol_requerido"],
            resumen_json=json.dumps(resumen, default=str, ensure_ascii=False),
            timeout_horas=self.ctx.settings.hitl_timeout_horas), "solicitar_aprobacion")
        log.info("HITL: solicitud %s (%s %s) — flujo en pausa", ap["aprobacion_id"], d["accion"], d["monto"])
        interrupt({"tipo": "APROBACION_HUMANA", "aprobacion_id": ap["aprobacion_id"], **resumen})
        final = hitl.obtener(ap["aprobacion_id"]) or {}
        log.info("HITL: reanudado, decisión registrada = %s", final.get("estado"))
        return {"aprobacion": {"aprobacion_id": ap["aprobacion_id"], "estado": final.get("estado", "PENDIENTE"),
                               "aprobador": final.get("aprobador"), "motivo": final.get("motivo")}}

    @nodo("ejecutar_accion")
    def ejecutar_accion(self, s):
        """ACCIÓN (efecto persistente) — solo llega aquí con aprobación humana APROBADA."""
        d, ap = s["decision_final"], s["aprobacion"]
        tool = "anular_transaccion" if d["accion"] == "ANULACION" else "registrar_reembolso"
        res = self.ctx.tools.llamar(tool, ticket_id=s["ticket_id"], transaccion_id=d["transaccion_objetivo_id"],
                                    aprobacion_id=ap["aprobacion_id"])
        if not res.get("ok"):
            codigo = res.get("error", {}).get("codigo")
            if codigo == "REQUIERE_OPERADOR":
                nueva = {**d, "accion": "ESCALAR_OPERADOR", "politicas": d["politicas"] + ["P-06"],
                         "motivo": "TARJETA_DESHABILITADA: un operador coordina el medio de reembolso"}
                return {"decision_final": nueva}
            if codigo == "YA_ANULADA":
                return {"salida": {"tipo": "RECHAZO_UNA_POR_RECLAMO", "datos": {}}, "resolucion": "RECHAZADO"}
        data = exigir(res, tool)
        if d["accion"] == "ANULACION":
            salida = {"tipo": "ANULADO", "datos": {"monto": data["monto"]}}
        else:
            salida = {"tipo": "REEMBOLSO_PROGRAMADO", "datos": {"monto": data["monto"],
                                                                  "fecha_estimada": data["fecha_estimada"],
                                                                  "sla": data.get("sla_dias_habiles", 7)}}
        return {"resultado_accion": data, "resolucion": d["accion"], "salida": salida}

    @nodo("escalar_operador")
    def escalar_operador(self, s):
        d, ap = s["decision_final"], s.get("aprobacion") or {}
        expiro = ap.get("estado") == "EXPIRADA"
        if expiro:
            tipo = "ESCALADO_HITL_EXPIRADO"
        elif s.get("discrepancias"):
            tipo = "ESCALADO_DISCREPANCIA"
        elif "P-06" in d["politicas"]:
            tipo = "ESCALADO_TARJETA"
        else:
            tipo = "ESCALADO"
        resumen = (
            f"Ticket: {s['ticket_id']}\nCliente: {s['cliente_id']}\nCaso: {s['caso_id']} / semilla {s['semilla']}\n"
            f"Motivo: {'APROBACION_HUMANA_EXPIRADA' if expiro else d['motivo']}\nPolíticas: {', '.join(d['politicas'])}\n"
            f"Discrepancias: {json.dumps(s.get('discrepancias') or [], ensure_ascii=False)}\n"
            f"Operación: {(s.get('tx') or {}).get('codigo_operacion', 'n/d')}\n"
            f"Alertas: {', '.join(d.get('alertas', [])) or 'ninguna'}")
        exigir(self.ctx.tools.llamar("escalar_operador", ticket_id=s["ticket_id"],
                                     motivo="HITL expirado" if expiro else d["motivo"].split(":")[0],
                                     resumen=resumen), "escalar_operador")
        return {"salida": {"tipo": tipo, "datos": {}}, "resolucion": "ESCALADO"}

    @nodo("finalizar")
    def finalizar(self, s):
        """Cierra el ticket según el resultado (o lo deja abierto si falta información)."""
        d, ap, t = s["decision_final"], s.get("aprobacion") or {}, self.ctx.tools
        salida, resolucion = s.get("salida") or {}, s.get("resolucion")
        if not salida:
            if ap.get("estado") == "RECHAZADA":
                salida = {"tipo": "HITL_RECHAZADO", "datos": {"motivo": ap.get("motivo")}}
                resolucion = "RECHAZADO"
            elif d["accion"] == "RECHAZAR":
                p = d["politicas"]
                tipo = "RECHAZO_AJENA" if "P-04" in p else "RECHAZO_UNA_POR_RECLAMO" if "P-05" in p else "RECHAZO"
                salida, resolucion = {"tipo": tipo, "datos": {}}, "RECHAZADO"
            elif d["accion"] == "NO_DISPONIBLE_MONEDA":
                salida, resolucion = {"tipo": "NO_DISPONIBLE_MONEDA", "datos": {}}, "INFORMATIVO"
            else:  # PEDIR_INFO: el ticket queda abierto esperando la evidencia
                salida = {"tipo": "PEDIR_INFO", "datos": {"imagen_error": s.get("imagen_error")}}
                exigir(t.llamar("actualizar_ticket", ticket_id=s["ticket_id"], estado="ABIERTO",
                                evento="INFORMACION_SOLICITADA",
                                detalle_json=json.dumps({"motivo": d["motivo"]}), actor="agente"),
                       "actualizar_ticket")
                return {"salida": salida}
        exigir(t.llamar("cerrar_ticket", ticket_id=s["ticket_id"], resolucion=resolucion), "cerrar_ticket")
        return {"salida": salida, "resolucion": resolucion}
