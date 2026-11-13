"""Contratos tipados (Pydantic) de las tools de consulta. El dato maestro sale SOLO de aquí."""
from __future__ import annotations

from pydantic import BaseModel


class TransaccionDTO(BaseModel):
    transaccion_id: str
    codigo_operacion: str
    pertenece_al_cliente: bool = True
    monto: float
    moneda: str
    fecha_hora: str
    estado: str
    anulada: bool
    canal: str
    grupo_duplicado: str | None = None
    empresa: str
    servicio: str
    tarjeta_ultimos4: str
    tarjeta_producto: str
    tarjeta_habilitada: bool
    dia_facturacion: int
    facturada: bool
    fecha_referencia: str


class TransaccionAjenaDTO(BaseModel):
    """Si la operación es de otro cliente NO se devuelve ningún detalle (política P-04 / privacidad)."""
    codigo_operacion: str
    pertenece_al_cliente: bool = False
