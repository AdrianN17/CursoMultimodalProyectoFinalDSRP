"""Motor de reglas de políticas de reclamación (P-01 … P-11). El motor DECIDE; el LLM explica.

Decisiones monetarias reproducibles y auditables: la misma entrada produce siempre la misma salida.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TOLERANCIA_MONTO = 0.005
INTENCIONES_RECLAMABLES = {"DUPLICADO", "SIN_CONSENTIMIENTO"}


@dataclass
class ContextoPolitica:
    otp_verificado: bool
    evidencia_valida: bool
    moneda: str | None
    monto_constancia: float | None
    intencion: str
    tx: dict[str, Any] | None  # dato maestro de la operación de la constancia
    duplicados: list[dict[str, Any]] = field(default_factory=list)  # operaciones del mismo grupo (del cliente)
    accion_previa_en_ticket: bool = False
    umbral_hitl: float = 1000.0
    intento_manipulacion: bool = False


@dataclass
class Decision:
    accion: str  # ANULACION | REEMBOLSO | ESCALAR_OPERADOR | PEDIR_INFO | RECHAZAR | NO_DISPONIBLE_MONEDA | INFORMAR
    politicas: list[str]
    motivo: str
    transaccion_objetivo_id: str | None = None
    monto: float | None = None
    requiere_hitl: bool = False
    rol_requerido: str | None = None
    discrepancias: list[dict[str, str]] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)

    def a_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def evaluar(c: ContextoPolitica) -> Decision:
    alertas = ["INTENTO_DE_MANIPULACION_DETECTADO"] if c.intento_manipulacion else []

    def d(accion: str, pol: list[str], motivo: str, **kw: Any) -> Decision:
        return Decision(accion=accion, politicas=pol, motivo=motivo, alertas=alertas, **kw)

    if not c.otp_verificado:
        return d("RECHAZAR", ["P-07"], "IDENTIDAD_NO_VERIFICADA")
    if c.moneda is not None and c.moneda != "PEN":
        return d("NO_DISPONIBLE_MONEDA", ["P-09"], "SOLO_SOLES: operación en moneda distinta de PEN")
    if not c.evidencia_valida:
        return d("PEDIR_INFO", ["P-02", "P-10"], "SIN_EVIDENCIA_VALIDA: no se puede reclamar sin constancia válida")
    tx = c.tx
    if tx is None:
        return d("ESCALAR_OPERADOR", ["P-10"], "OPERACION_INEXISTENTE_EN_BD",
                 discrepancias=[{"campo": "codigo_operacion", "percibido": "presente en constancia",
                                 "maestro": "no existe"}])
    if not tx["pertenece_al_cliente"]:
        return d("RECHAZAR", ["P-04"], "OPERACION_AJENA: no se pueden anular transacciones que no son del cliente")
    if c.monto_constancia is not None and abs(c.monto_constancia - float(tx["monto"])) > TOLERANCIA_MONTO:
        return d("ESCALAR_OPERADOR", ["P-10"],
                 "DISCREPANCIA_DE_MONTO: prevalece el dato maestro; se registra y escala",
                 discrepancias=[{"campo": "monto", "percibido": f"{c.monto_constancia:.2f}",
                                 "maestro": f"{float(tx['monto']):.2f}"}])
    if c.intencion not in INTENCIONES_RECLAMABLES:
        return d("ESCALAR_OPERADOR", ["P-01"], f"MOTIVO_NO_CUBIERTO_AUTOMATICAMENTE ({c.intencion})")

    if c.intencion == "SIN_CONSENTIMIENTO" and tx.get("autenticada_otp", True):
        return d("ESCALAR_OPERADOR", ["P-11"],
                 "OPERACION_AUTENTICADA_CON_OTP: el cliente desconoce una operación validada con su OTP; "
                 "posible ingeniería social, no se reembolsa de forma automática")

    objetivo = tx
    if c.intencion == "DUPLICADO":
        vigentes = [x for x in c.duplicados if not x["anulada"]]
        if len(vigentes) < 2:
            return d("ESCALAR_OPERADOR", ["P-01"], "DUPLICIDAD_NO_EVIDENCIADA_EN_BD")
        objetivo = max(vigentes, key=lambda x: x["fecha_hora"])  # se anula la repetida (la última)
    if objetivo["anulada"] or c.accion_previa_en_ticket:
        return d("RECHAZAR", ["P-05"], "SOLO_UNA_ANULACION_POR_RECLAMO (ya existe una acción para este ticket)")
    if not tx["tarjeta_habilitada"]:
        return d("ESCALAR_OPERADOR", ["P-06"],
                 "TARJETA_DESHABILITADA: un operador coordina el medio de reembolso",
                 transaccion_objetivo_id=objetivo["transaccion_id"], monto=float(objetivo["monto"]))

    monto = float(objetivo["monto"])
    rol = "SUPERVISOR" if monto >= c.umbral_hitl else "ANALISTA"
    if tx["facturada"]:
        return d("REEMBOLSO", ["P-01"], "RECLAMO_VALIDO_FACTURADO: reembolso en 7 días hábiles",
                 transaccion_objetivo_id=objetivo["transaccion_id"], monto=monto, requiere_hitl=True,
                 rol_requerido=rol)
    return d("ANULACION", ["P-03", "P-01"], "RECLAMO_VALIDO_ANTES_DE_FACTURACION: anulación",
             transaccion_objetivo_id=objetivo["transaccion_id"], monto=monto, requiere_hitl=True,
             rol_requerido=rol)
