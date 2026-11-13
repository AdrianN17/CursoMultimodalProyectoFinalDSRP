"""Nodos de DATOS e INFERENCIA: ticket idempotente, dato maestro (MCP), cruce de evidencias, políticas, RAG y agente."""
from __future__ import annotations

import hashlib
import logging

from ...politicas.motor import ContextoPolitica, evaluar
from ..base import exigir, nodo

log = logging.getLogger("reclamos.nodos.datos")
ESTADOS_YA_ATENDIDOS = {"CERRADO", "EN_ESCALAMIENTO", "PENDIENTE_APROBACION"}
ACCIONES_MONETARIAS = {"ANULACION", "REEMBOLSO"}
CONFIANZA_MINIMA_MONETARIA = 0.6


class DatosMixin:
    @nodo("abrir_ticket")
    def abrir_ticket(self, s):
        t = self.ctx.tools
        cons = s.get("constancia") or {}
        codigo = cons.get("codigo_operacion") or (s.get("intencion") or {}).get("codigo_operacion_mencionado")
        idem = s.get("idem_key") or f"{s['sesion_id']}|{codigo or 'sin-op'}"
        data = exigir(t.llamar("crear_ticket", cliente_id=s["cliente_id"],
                               tipo_reclamo=(s.get("intencion") or {}).get("intencion", "OTRO"),
                               idem_key=idem, caso_id=s["caso_id"], semilla=s["semilla"], thread_id=s["sesion_id"]),
                      "crear_ticket", permitidos=("IDEMPOTENCY_CONFLICT",))
        if data is None:
            return {"error_usuario": {"codigo": "IDEMPOTENCY_CONFLICT", "mensaje": "idem_key reutilizada"}}
        ticket_id = data["ticket_id"]
        for tipo, sha, ruta, extra in (
            ("texto", hashlib.sha256((s.get("transcripcion") or "").encode()).hexdigest(), "", {}),
            ("audio", s.get("hash_audio"), s.get("audio_path"), {}),
            ("imagen", s.get("hash_imagen"), s.get("imagen_path"), s.get("constancia") or {}),
        ):
            if sha:
                import json
                from pathlib import Path
                exigir(t.llamar("registrar_evidencia", ticket_id=ticket_id, tipo=tipo, sha256=sha,
                                ruta=Path(ruta).name if ruta else "", extraccion_json=json.dumps(extra, default=str),
                                valida=bool(extra.get("valida", True)) if tipo == "imagen" else True),
                      "registrar_evidencia")
        ya = (not data["creado"]) and data["estado"] in ESTADOS_YA_ATENDIDOS
        log.info("ticket %s (creado=%s, estado=%s)", ticket_id, data["creado"], data["estado"])
        return {"ticket_id": ticket_id, "ticket_creado": data["creado"], "ticket_ya_resuelto": ya}

    @nodo("consultar_maestro")
    def consultar_maestro(self, s):
        t = self.ctx.tools
        parametros = exigir(t.llamar("consultar_parametros"), "consultar_parametros")
        cons = s.get("constancia")
        tx, dup = None, []
        if cons and cons.get("valida") and cons.get("moneda") == "PEN":
            tx = exigir(t.llamar("consultar_transaccion", cliente_id=s["cliente_id"],
                                 codigo_operacion=cons["codigo_operacion"]),
                        "consultar_transaccion", permitidos=("NO_ENCONTRADA",))
            if tx and tx.get("pertenece_al_cliente") and tx.get("grupo_duplicado"):
                dup = exigir(t.llamar("buscar_duplicados", cliente_id=s["cliente_id"],
                                      transaccion_id=tx["transaccion_id"]), "buscar_duplicados")["items"]
        tk = exigir(t.llamar("consultar_ticket", ticket_id=s["ticket_id"]), "consultar_ticket")
        propia = bool(tx and tx.get("pertenece_al_cliente"))
        exigir(t.llamar("actualizar_ticket", ticket_id=s["ticket_id"], estado="EN_ANALISIS",
                        transaccion_id=tx["transaccion_id"] if propia else "", evento="MAESTRO_CONSULTADO",
                        detalle_json='{"operacion_encontrada": %s}' % str(propia).lower(), actor="agente"),
               "actualizar_ticket")
        return {"tx": tx, "duplicados": dup, "parametros": parametros,
                "ticket_accion_previa": tk["ticket"]["accion_ejecutada"] is not None}

    @nodo("cruzar_evidencias")
    def cruzar_evidencias(self, s):
        """Compara relato ↔ imagen ↔ BD. Una contradicción se REGISTRA (autoridad: dato maestro); no se corrige."""
        tx, cons, intencion = s.get("tx"), s.get("constancia") or {}, s.get("intencion") or {}
        propia = bool(tx and tx.get("pertenece_al_cliente"))
        comp = {"monto_relato": intencion.get("monto_mencionado"), "monto_imagen": cons.get("monto"),
                "monto_bd": tx.get("monto") if propia else None, "coincide": None}
        discrepancias = []
        if propia and comp["monto_imagen"] is not None:
            comp["coincide"] = abs(comp["monto_imagen"] - comp["monto_bd"]) < 0.005
            if not comp["coincide"]:
                discrepancias.append({"campo": "monto", "percibido": f"{comp['monto_imagen']:.2f}",
                                      "maestro": f"{comp['monto_bd']:.2f}"})
                exigir(self.ctx.tools.llamar("registrar_discrepancia", ticket_id=s["ticket_id"], campo="monto",
                                             percibido=discrepancias[0]["percibido"],
                                             maestro=discrepancias[0]["maestro"], accion="ESCALAR_OPERADOR"),
                       "registrar_discrepancia")
                log.warning("CONTRADICCIÓN: constancia=%s vs BD=%s -> prevalece el dato maestro; se escala",
                            discrepancias[0]["percibido"], discrepancias[0]["maestro"])
        return {"comparacion": comp, "discrepancias": discrepancias}

    @nodo("evaluar_politicas")
    def evaluar_politicas(self, s):
        cons, intencion = s.get("constancia"), s.get("intencion") or {}
        moneda = cons.get("moneda") if cons else None
        if "USD" in (moneda, intencion.get("moneda_mencionada")):
            moneda = "USD"
        ctx = ContextoPolitica(
            otp_verificado=True,
            evidencia_valida=bool(cons and cons.get("valida")),
            moneda=moneda or intencion.get("moneda_mencionada"),
            monto_constancia=cons.get("monto") if cons else None,
            intencion=intencion.get("intencion", "OTRO"),
            tx=s.get("tx"),
            duplicados=s.get("duplicados") or [],
            accion_previa_en_ticket=bool(s.get("ticket_accion_previa")),
            umbral_hitl=float((s.get("parametros") or {}).get("umbral_hitl", 1000)),
            intento_manipulacion=bool(intencion.get("intento_manipulacion")),
        )
        d = evaluar(ctx)
        log.info("motor de políticas: %s %s (%s)", d.accion, d.politicas, d.motivo)
        return {"decision": d.a_dict()}

    @nodo("recuperar_politica")
    def recuperar_politica(self, s):
        d = s["decision"]
        consulta = f"{d['motivo']} {(s.get('intencion') or {}).get('intencion', '')}"
        return {"politicas": self.ctx.retriever.buscar(consulta, k=3, obligatorias=d["politicas"])}

    @nodo("analizar_agente")
    def analizar_agente(self, s):
        d = dict(s["decision"])
        if d["accion"] == "NO_DISPONIBLE_MONEDA":  # decisión trivial: no se gasta una llamada al modelo
            return {"inferencia": None, "decision_final": d}
        tx = s.get("tx") or {}
        propia = bool(tx.get("pertenece_al_cliente"))
        maestro = None if not tx else (
            {"pertenece_al_cliente": False} if not propia else
            {k: tx[k] for k in ("monto", "fecha_hora", "estado", "anulada", "canal", "tarjeta_habilitada", "facturada",
                                "grupo_duplicado", "pertenece_al_cliente")})
        cons = s.get("constancia")
        payload = {
            "transcripcion": s.get("transcripcion", ""), "origen_relato": s.get("origen_relato", "texto"),
            "intencion": s.get("intencion"),
            "constancia": ({k: cons[k] for k in ("monto", "moneda", "codigo_operacion", "fecha", "empresa")}
                           if cons and cons.get("valida") else None),
            "maestro": maestro, "duplicados": s.get("duplicados") or [],
            "politicas": [{"id": p["policy_id"], "texto": p["texto"]} for p in s.get("politicas", [])],
            "memoria": s.get("memoria_resumen", ""),
        }
        salida = self.ctx.agente.analizar(payload)
        # El motor DECIDE: el agente solo puede coincidir o forzar una escalada más conservadora.
        d["alertas"] = list(d.get("alertas", []))
        if d["accion"] in ACCIONES_MONETARIAS:
            if salida.accion_propuesta != d["accion"]:
                d.update(accion="ESCALAR_OPERADOR", requiere_hitl=False,
                         motivo=f"INCONSISTENCIA_AGENTE_MOTOR: agente={salida.accion_propuesta} motor={d['accion']}")
                d["alertas"].append("INCONSISTENCIA_AGENTE_MOTOR")
            elif salida.confianza < CONFIANZA_MINIMA_MONETARIA:
                d.update(accion="ESCALAR_OPERADOR", requiere_hitl=False,
                         motivo=f"CONFIANZA_BAJA ({salida.confianza:.2f}) en acción monetaria")
                d["alertas"].append("CONFIANZA_BAJA")
        elif salida.accion_propuesta in ACCIONES_MONETARIAS:
            d["alertas"].append("AGENTE_PROPUSO_ACCION_NO_AUTORIZADA_POR_POLITICA")
            log.warning("el agente propuso %s pero la política no lo permite: se ignora", salida.accion_propuesta)
        log.info("agente: inferencia=%s propone=%s confianza=%.2f | decisión final=%s", salida.inferencia,
                 salida.accion_propuesta, salida.confianza, d["accion"])
        return {"inferencia": salida.model_dump(), "decision_final": d}
