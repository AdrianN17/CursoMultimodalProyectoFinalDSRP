"""Nodos de PERCEPCIÓN: validación de entrada, STT, intención, identidad (OTP) y visión."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from ...modalidades.validacion_archivos import ArchivoInvalido, validar_audio, validar_imagen
from ...seguridad.otp import verificar_otp
from ...validadores.constancia import validar_constancia
from ..base import nodo

log = logging.getLogger("reclamos.nodos.entrada")

# Claves que NO deben arrastrarse de un turno anterior (el ticket y la memoria sí se conservan).
REINICIO_TURNO = {
    "error": None, "error_usuario": None, "decision": {}, "decision_final": {}, "inferencia": None,
    "aprobacion": None, "resultado_accion": None, "resolucion": None, "salida": {}, "respuesta": {},
    "politicas": [], "discrepancias": [], "comparacion": {}, "tx": None, "duplicados": [], "ticket_creado": False,
    "ticket_ya_resuelto": False, "constancia": None, "intencion": {}, "transcripcion": "", "audio_respuesta": None,
    "audio_ok": False, "imagen_ok": False, "imagen_error": None, "hash_audio": None, "hash_imagen": None,
    "origen_relato": "texto", "ticket_accion_previa": False,
}


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


class EntradaMixin:
    @nodo("validar_entrada")
    def validar_entrada(self, s):
        cfg = self.ctx.settings
        out = {**REINICIO_TURNO, "turno": s.get("turno", 0) + 1}
        texto = (s.get("texto") or "").strip()
        out["transcripcion"] = texto

        if s.get("audio_path"):
            try:
                validar_audio(Path(s["audio_path"]), cfg.max_upload_mb)
                out["audio_ok"] = True
                out["hash_audio"] = _sha(Path(s["audio_path"]))
            except ArchivoInvalido as e:
                log.warning("audio rechazado: %s", e.codigo)
                if not texto:
                    out["error_usuario"] = {"codigo": e.codigo, "mensaje": e.mensaje}
                    return out
        if s.get("imagen_path"):
            try:
                validar_imagen(Path(s["imagen_path"]), cfg.max_upload_mb)
                out["imagen_ok"] = True
                out["hash_imagen"] = _sha(Path(s["imagen_path"]))
            except ArchivoInvalido as e:  # degradación controlada: se sigue SIN imagen y se pide evidencia
                log.warning("imagen rechazada: %s", e.codigo)
                out["imagen_error"] = e.codigo
        if not texto and not out["audio_ok"]:
            out["error_usuario"] = {"codigo": "SIN_ENTRADA", "mensaje": "No hay texto ni audio"}
        return out

    @nodo("stt")
    def stt(self, s):
        dicho = self.ctx.prov.transcribir(Path(s["audio_path"])).strip()
        if not dicho and not s.get("transcripcion"):
            log.warning("STT devolvió vacío: audio ininteligible")
            return {"error_usuario": {"codigo": "AUDIO_ININTELIGIBLE", "mensaje": "Transcripción vacía"}}
        texto = f"{s.get('transcripcion', '')} {dicho}".strip()
        return {"transcripcion": texto, "origen_relato": "audio" if dicho else "texto"}

    @nodo("clasificar_intencion")
    def clasificar_intencion(self, s):
        i = self.ctx.agente.clasificar_intencion(s.get("transcripcion", ""))
        if i.intento_manipulacion:
            log.warning("posible intento de manipulación en el relato (se ignora; decide el motor de reglas)")
        return {"intencion": i.model_dump()}

    @nodo("verificar_otp")
    def verificar_otp(self, s):
        ok, motivo = verificar_otp(s["sesion_id"], s["cliente_id"], s.get("otp_codigo"))
        log.info("verificación de identidad: %s", motivo)
        return {} if ok else {"error_usuario": {"codigo": motivo, "mensaje": "Identidad no verificada"}}

    @nodo("vision_constancia")
    def vision_constancia(self, s):
        crudo = self.ctx.prov.extraer_constancia(Path(s["imagen_path"]))
        r = validar_constancia(crudo)
        log.info("constancia: valida=%s errores=%s moneda=%s", r.valida, r.errores, r.moneda)
        return {"constancia": r.a_dict(), "imagen_error": None if r.valida else (r.errores[0] if r.errores else None)}
