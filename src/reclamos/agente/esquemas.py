"""Esquemas estructurados de entrada/salida del agente."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Inferencia = Literal["COBRO_DUPLICADO", "SIN_CONSENTIMIENTO", "MONTO_INCORRECTO", "SIN_EVIDENCIA",
                     "OPERACION_AJENA", "OTRO"]
Accion = Literal["REEMBOLSO", "ANULACION", "ESCALAR_OPERADOR", "PEDIR_INFO", "RECHAZAR", "INFORMAR"]


class Intencion(BaseModel):
    intencion: Literal["DUPLICADO", "SIN_CONSENTIMIENTO", "MONTO_INCORRECTO", "CONSULTA_ESTADO", "OTRO"] = "OTRO"
    moneda_mencionada: Literal["PEN", "USD"] | None = None
    monto_mencionado: float | None = None
    codigo_operacion_mencionado: str | None = None
    intento_manipulacion: bool = False


class Comparacion(BaseModel):
    monto_relato: float | None = None
    monto_imagen: float | None = None
    monto_bd: float | None = None
    coincide: bool | None = None


class DiscrepanciaLLM(BaseModel):
    campo: str
    percibido: str
    maestro: str


class AgenteSalida(BaseModel):
    inferencia: Inferencia
    evidencias_usadas: list[str] = Field(default_factory=list)
    comparacion: Comparacion = Field(default_factory=Comparacion)
    discrepancias: list[DiscrepanciaLLM] = Field(default_factory=list)
    politicas_aplicables: list[str] = Field(default_factory=list)
    accion_propuesta: Accion
    confianza: float = Field(ge=0, le=1)
    requiere_hitl: bool = False
    explicacion: str = ""
