"""Identidad del cliente: emisión/verificación de OTP y rastro de logins (LoginTrack, OtpChallenge)."""
from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timedelta, timezone

from .. import db
from ..config import get_settings
from ..escenario import construir_escenario

log = logging.getLogger("reclamos.otp")
OTP_TTL_MINUTOS = 10
OTP_MAX_INTENTOS = 3


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(otp_id: str, codigo: str) -> str:
    return hashlib.sha256(f"{otp_id}:{codigo}".encode()).hexdigest()


def registrar_login(cliente_id: str, sesion_id: str, canal: str, resultado: str, ip: str = "") -> None:
    ip_hash = hashlib.sha256(ip.encode()).hexdigest() if ip else None
    db.ejecutar("INSERT INTO LoginTrack (cliente_id, sesion_id, canal, ip_hash, resultado) VALUES (?, ?, ?, ?, ?)",
                (cliente_id, sesion_id, canal, ip_hash, resultado))


def emitir_otp(cliente_id: str, sesion_id: str, caso_id: str, semilla: int, canal: str = "web") -> dict:
    """El código viene del escenario (semilla, elemento 7). En producción lo enviaría un proveedor SMS/correo."""
    codigo = construir_escenario(caso_id, semilla).otp
    otp_id = "OTP-" + uuid.uuid4().hex[:10].upper()
    db.ejecutar(
        "INSERT INTO OtpChallenge (otp_id, cliente_id, sesion_id, proposito, otp_hash, expira_en) "
        "VALUES (?, ?, ?, 'RECLAMO', ?, ?)",
        (otp_id, cliente_id, sesion_id, _hash(otp_id, codigo), _ahora() + timedelta(minutes=OTP_TTL_MINUTOS)))
    registrar_login(cliente_id, sesion_id, canal, "OTP_EMITIDO")
    log.info("OTP emitido para sesión %s (código no se registra)", sesion_id)
    out = {"otp_id": otp_id, "expira_en_minutos": OTP_TTL_MINUTOS}
    if get_settings().demo_mode:
        out["otp_demo"] = codigo  # SOLO modo demo: simula el SMS recibido por el cliente
    return out


def sesion_verificada(sesion_id: str) -> bool:
    return db.uno("SELECT 1 AS x FROM OtpChallenge WHERE sesion_id = ? AND estado = 'VERIFICADO'",
                  (sesion_id,)) is not None


def verificar_otp(sesion_id: str, cliente_id: str, codigo: str | None) -> tuple[bool, str]:
    """Devuelve (ok, motivo). Máx. 3 intentos y expiración de 10 minutos."""
    if sesion_verificada(sesion_id):
        return True, "YA_VERIFICADA"
    ch = db.uno("SELECT TOP 1 * FROM OtpChallenge WHERE sesion_id = ? AND cliente_id = ? ORDER BY creado_en DESC",
                (sesion_id, cliente_id))
    if not ch:
        return False, "SIN_OTP_EMITIDO"
    if not codigo:
        return False, "OTP_REQUERIDO"
    if ch["estado"] in ("FALLIDO", "EXPIRADO"):
        return False, f"OTP_{ch['estado']}"
    if ch["expira_en"] < _ahora():
        db.ejecutar("UPDATE OtpChallenge SET estado = 'EXPIRADO' WHERE otp_id = ?", (ch["otp_id"],))
        registrar_login(cliente_id, sesion_id, "web", "OTP_EXPIRADO")
        return False, "OTP_EXPIRADO"
    if hmac.compare_digest(ch["otp_hash"], _hash(ch["otp_id"], codigo.strip())):
        db.ejecutar("UPDATE OtpChallenge SET estado = 'VERIFICADO', verificado_en = SYSUTCDATETIME(), "
                    "intentos = intentos + 1 WHERE otp_id = ?", (ch["otp_id"],))
        registrar_login(cliente_id, sesion_id, "web", "OTP_OK")
        return True, "OTP_OK"
    intentos = ch["intentos"] + 1
    estado = "FALLIDO" if intentos >= OTP_MAX_INTENTOS else "PENDIENTE"
    db.ejecutar("UPDATE OtpChallenge SET intentos = ?, estado = ? WHERE otp_id = ?", (intentos, estado, ch["otp_id"]))
    registrar_login(cliente_id, sesion_id, "web", "OTP_FALLIDO")
    return False, "OTP_INCORRECTO" if estado == "PENDIENTE" else "OTP_BLOQUEADO"
