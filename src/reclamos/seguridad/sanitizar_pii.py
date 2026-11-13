"""Enmascarado de PII. Nada de esto debe llegar al modelo ni a los logs en claro."""
from __future__ import annotations

import re
from typing import Any

_RE_TARJETA = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_RE_EMAIL = re.compile(r"\b([\w.+-])[\w.+-]*@([\w-]+\.[\w.]+)\b")
_RE_OTP = re.compile(r"(?i)(otp|c[oó]digo de verificaci[oó]n)\W{0,3}\d{4,8}")
_RE_DNI = re.compile(r"(?i)\b(dni|documento)\W{0,3}\d{8}\b")
_CLAVES_SENSIBLES = {"otp", "otp_codigo", "password", "pwd", "api_key", "cvv", "doc", "doc_hash"}


def enmascarar_tarjeta(numero: str) -> str:
    digitos = re.sub(r"\D", "", numero)
    return f"****{digitos[-4:]}" if len(digitos) >= 4 else "****"


def enmascarar_texto(texto: str) -> str:
    texto = _RE_OTP.sub(lambda m: f"{m.group(1)} ******", texto)
    texto = _RE_DNI.sub(lambda m: f"{m.group(1)} ********", texto)
    texto = _RE_EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", texto)
    texto = _RE_TARJETA.sub(lambda m: enmascarar_tarjeta(m.group(0)), texto)
    return texto


def sanitizar(obj: Any) -> Any:
    """Copia recursiva con PII enmascarada (se usa antes de cada llamada al LLM y en atributos de trazas)."""
    if isinstance(obj, str):
        return enmascarar_texto(obj)
    if isinstance(obj, dict):
        return {k: ("***" if str(k).lower() in _CLAVES_SENSIBLES else sanitizar(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitizar(v) for v in obj]
    return obj
