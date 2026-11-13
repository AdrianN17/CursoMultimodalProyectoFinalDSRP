"""Calendario de facturación y plazos (reglas de negocio puras, sin I/O)."""
from __future__ import annotations

from datetime import date, timedelta


def ultimo_corte(fecha_ref: date, dia_facturacion: int) -> date:
    """Última fecha de corte (día `dia_facturacion`) menor o igual a la fecha de referencia."""
    if fecha_ref.day >= dia_facturacion:
        return fecha_ref.replace(day=dia_facturacion)
    mes_anterior = fecha_ref.replace(day=1) - timedelta(days=1)
    return mes_anterior.replace(day=dia_facturacion)


def esta_facturada(fecha_operacion: date, fecha_ref: date, dia_facturacion: int) -> bool:
    """True si la operación ya quedó incluida en un corte (no es anulable por P-03)."""
    return fecha_operacion <= ultimo_corte(fecha_ref, dia_facturacion)


def sumar_dias_habiles(inicio: date, dias: int) -> date:
    actual = inicio
    restantes = dias
    while restantes > 0:
        actual += timedelta(days=1)
        if actual.weekday() < 5:
            restantes -= 1
    return actual
