"""Textos hablados (TTS). Plantillas determinísticas: montos, fechas y estados salen del dato maestro, nunca del LLM."""
from __future__ import annotations

from typing import Any

ESTADO_TXT = {
    "ABIERTO": "abierto y en espera de información",
    "EN_ANALISIS": "en análisis",
    "PENDIENTE_APROBACION": "en revisión por un analista",
    "EN_ESCALAMIENTO": "derivado a un operador, que se comunicará con usted por correo",
    "PENDIENTE_TECNICO": "pendiente por un inconveniente técnico",
    "CERRADO": "cerrado",
}
RESOLUCION_TXT = {
    "REEMBOLSO": "con reembolso aprobado",
    "ANULACION": "con la operación anulada",
    "RECHAZADO": "sin proceder la solicitud",
    "INFORMATIVO": "de forma informativa",
    "ESCALADO": "derivado a un operador",
    "EXPIRADO": "derivado a un operador por falta de respuesta del revisor",
}
ERRORES_USUARIO = {
    "VIDEO_NO_PERMITIDO": "No aceptamos videos. Por favor envíe una imagen de su constancia de pago.",
    "ARCHIVO_MUY_GRANDE": "El archivo es demasiado grande. Envíe uno más liviano.",
    "AUDIO_ININTELIGIBLE": "No logramos escuchar con claridad su mensaje. ¿Puede repetirlo o escribirlo?",
    "SIN_ENTRADA": "No recibimos ningún mensaje. Cuéntenos por voz o texto qué ocurrió con su operación.",
    "OTP_REQUERIDO": "Para continuar necesitamos el código de verificación que le enviamos.",
    "OTP_INCORRECTO": "El código de verificación no es correcto. Inténtelo nuevamente.",
    "OTP_BLOQUEADO": "Superó los intentos permitidos. Solicite un nuevo código de verificación.",
    "OTP_EXPIRADO": "El código de verificación venció. Solicite uno nuevo.",
    "SIN_OTP_EMITIDO": "No pudimos verificar su identidad. Inicie una nueva sesión.",
    "SIN_RECLAMO": "No encontramos un reclamo previo en esta conversación. Cuéntenos qué ocurrió con su operación.",
    "IDEMPOTENCY_CONFLICT": "Esa solicitud ya se usó con otros datos. Envíe su reclamo nuevamente.",
}
PEDIR_INFO_IMAGEN = {
    "VIDEO_NO_PERMITIDO": "No aceptamos videos; envíe una imagen de la constancia de pago.",
    "CONTENIDO_NO_ES_IMAGEN": "El archivo no es una imagen válida. Envíe una captura o foto de su constancia de pago.",
    "IMAGEN_CORRUPTA": "No pudimos abrir la imagen. Envíe nuevamente su constancia de pago.",
    "IMAGEN_MUY_PEQUENA": "La imagen es muy pequeña para leerla. Envíe una captura completa de la constancia.",
    "EXTENSION_NO_PERMITIDA": "Solo aceptamos imágenes JPG o PNG de su constancia de pago.",
    "ARCHIVO_MUY_GRANDE": "La imagen es demasiado grande. Envíe una más liviana.",
}


def _monto(m: float | None) -> str:
    return f"{m:,.2f} soles" if m is not None else "el monto indicado"


def texto_para(tipo: str, d: dict[str, Any]) -> str:
    t = d.get("ticket_id")
    ref = f" Su número de atención es {t}." if t else ""
    if tipo == "ANULADO":
        return (f"Su reclamo fue aprobado. Anulamos la operación por {_monto(d.get('monto'))} y el saldo "
                f"disponible ya fue restituido.{ref}")
    if tipo == "REEMBOLSO_PROGRAMADO":
        return (f"Su reclamo fue aprobado. Programamos el reembolso de {_monto(d.get('monto'))}; llegará en "
                f"{d.get('sla', 7)} días hábiles, alrededor del {d.get('fecha_estimada')}.{ref}")
    if tipo == "PENDIENTE_APROBACION":
        return f"Registramos su reclamo. Un analista revisará su caso y le informaremos el resultado.{ref}"
    if tipo == "HITL_RECHAZADO":
        return (f"Un analista revisó su reclamo y no pudo aprobarlo. Motivo: {d.get('motivo') or 'no especificado'}."
                f"{ref}")
    if tipo == "ESCALADO_DISCREPANCIA":
        return (f"Encontramos una diferencia entre su constancia y nuestros registros, por eso su caso será revisado "
                f"por un operador, que se comunicará con usted por correo.{ref}")
    if tipo == "ESCALADO_TARJETA":
        return (f"La tarjeta de la compra no está habilitada, por lo que un operador coordinará con usted el medio de "
                f"reembolso por correo.{ref}")
    if tipo == "ESCALADO_OTP":
        return (f"Esa operación fue confirmada con su código de verificación, por lo que su caso será revisado "
                f"por un operador, que se comunicará con usted por correo.{ref}")
    if tipo == "ESCALADO_HITL_EXPIRADO":
        return f"Su reclamo no pudo ser revisado a tiempo y fue derivado a un operador, que se comunicará con usted.{ref}"
    if tipo == "ESCALADO":
        return f"Su caso requiere la revisión de un operador, que se comunicará con usted por correo.{ref}"
    if tipo == "RECHAZO_AJENA":
        return f"No podemos atender esta solicitud porque la operación no corresponde a su cuenta.{ref}"
    if tipo == "RECHAZO_UNA_POR_RECLAMO":
        return f"Este reclamo ya tiene una anulación o reembolso. Solo se permite uno por reclamo.{ref}"
    if tipo == "RECHAZO":
        return f"No es posible atender esta solicitud según nuestras políticas.{ref}"
    if tipo == "PEDIR_INFO":
        detalle = PEDIR_INFO_IMAGEN.get(d.get("imagen_error") or "", "")
        return (f"Para continuar necesitamos una constancia de pago válida, con fecha, tarjeta, empresa, código de "
                f"operación y monto en soles. {detalle}{ref}").replace("  ", " ")
    if tipo == "NO_DISPONIBLE_MONEDA":
        return ("Por ahora esta opción no está disponible para operaciones en dólares. Por favor use el canal "
                f"regular.{ref}")
    if tipo == "ERROR_USUARIO":
        return ERRORES_USUARIO.get(d.get("codigo", ""), "No pudimos procesar su solicitud. Inténtelo nuevamente.")
    if tipo == "ERROR_TECNICO":
        return ("Tuvimos un inconveniente técnico. " + (f"Su atención {t} quedó registrada y la revisaremos "
                                                        "a la brevedad." if t else "Inténtelo nuevamente en unos minutos."))
    if tipo == "ESTADO":
        estado = ESTADO_TXT.get(d.get("estado", ""), d.get("estado", ""))
        extra = f", {RESOLUCION_TXT[d['resolucion']]}" if d.get("estado") == "CERRADO" and d.get("resolucion") in \
            RESOLUCION_TXT else ""
        fecha = f" El reembolso está programado para el {d['fecha_estimada']}." if d.get("fecha_estimada") else ""
        return f"Su reclamo {t} se encuentra {estado}{extra}.{fecha}"
    return "Gracias por comunicarse con nosotros."
