"""Carga en la BD el escenario sintético derivado de CASO_ID + SEMILLA (elementos 1-5 y 7 de la semilla).

Uso:  python scripts/seed_db.py --caso-id C-07 --semilla 4213 [--tipo DUPLICADA]
Reemplaza los datos de negocio y de proceso (no toca el catálogo de servicios ni los checkpoints).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from reclamos import db  # noqa: E402
from reclamos.config import get_settings  # noqa: E402
from reclamos.escenario import CATALOGO_SERVICIOS, Escenario, construir_escenario  # noqa: E402

log = logging.getLogger("reclamos.seed")

# Orden hijo -> padre para limpiar sin violar FKs
TABLAS_NEGOCIO = [
    "Discrepancia", "Evidencia", "Reembolso", "AprobacionHitl", "TicketEvento",
    "IdempotencyKey", "Ticket", "Sesion", "Transaccion", "Tarjeta", "Balance",
    "Cuenta", "Cliente", "ParametroEscenario",
]


def limpiar(cn) -> None:
    for t in TABLAS_NEGOCIO:
        cn.cursor().execute(f"DELETE FROM {t}")
    log.debug("BD: %d tablas de negocio vaciadas", len(TABLAS_NEGOCIO))


def cargar(esc: Escenario) -> None:
    log.info("BD: cargando el escenario %s/%s tipo=%s (%d clientes, %d cuentas, %d tarjetas, %d transacciones)",
             esc.caso_id, esc.semilla, esc.tipo, len(esc.clientes), len(esc.cuentas), len(esc.tarjetas),
             len(esc.transacciones))
    with db.conexion() as cn:
        limpiar(cn)
        c = cn.cursor()
        for s in CATALOGO_SERVICIOS:
            c.execute(
                "IF NOT EXISTS (SELECT 1 FROM Servicio WHERE servicio_id = ?) "
                "INSERT INTO Servicio (servicio_id, empresa, servicio, categoria) VALUES (?, ?, ?, ?)",
                (s.servicio_id, s.servicio_id, s.empresa, s.servicio, s.categoria),
            )
        for cl in esc.clientes:
            c.execute(
                "INSERT INTO Cliente (cliente_id, nombre_mask, doc_hash, email_mask, segmento, caso_id, semilla) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cl.cliente_id, cl.nombre_mask, cl.doc_hash, cl.email_mask, cl.segmento, esc.caso_id, esc.semilla),
            )
        for cu in esc.cuentas:
            c.execute("INSERT INTO Cuenta (cuenta_id, cliente_id, tipo, moneda) VALUES (?, ?, ?, 'PEN')",
                      (cu.cuenta_id, cu.cliente_id, cu.tipo))
            c.execute("INSERT INTO Balance (cuenta_id, saldo, saldo_disponible) VALUES (?, ?, ?)",
                      (cu.cuenta_id, cu.saldo, cu.saldo_disponible))
        for t in esc.tarjetas:
            c.execute(
                "INSERT INTO Tarjeta (tarjeta_id, cuenta_id, ultimos4, producto, habilitada, dia_facturacion) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t.tarjeta_id, t.cuenta_id, t.ultimos4, t.producto, int(t.habilitada), t.dia_facturacion),
            )
        for tx in esc.transacciones:
            c.execute(
                "INSERT INTO Transaccion (transaccion_id, codigo_operacion, tarjeta_id, servicio_id, monto, "
                "moneda, fecha_hora, canal, grupo_duplicado, autenticada_otp) "
                "VALUES (?, ?, ?, ?, ?, 'PEN', ?, ?, ?, ?)",
                (tx.transaccion_id, tx.codigo_operacion, tx.tarjeta_id, tx.servicio_id, tx.monto,
                 tx.fecha_hora, tx.canal, tx.grupo_duplicado, int(tx.autenticada_otp)),
            )
        params = {
            "caso_id": esc.caso_id,
            "semilla": str(esc.semilla),
            "fecha_referencia": esc.fecha_referencia.isoformat(),
            "umbral_hitl": str(esc.umbral_hitl),
            "tipo_caso": esc.tipo,
        }
        for k, v in params.items():
            c.execute("INSERT INTO ParametroEscenario (clave, valor) VALUES (?, ?)", (k, v))
    log.info("BD: escenario cargado (umbral HITL=%s, accion esperada=%s)", esc.umbral_hitl, esc.accion_esperada)


def resumen(esc: Escenario) -> str:
    return (
        f"CASO_ID={esc.caso_id} SEMILLA={esc.semilla} tipo={esc.tipo} cliente={esc.cliente_id} "
        f"op_constancia={esc.tx_principal_codigo} op_objetivo={esc.tx_objetivo_codigo} monto_bd=S/{esc.monto_bd} "
        f"facturada={esc.facturada} umbral_hitl={esc.umbral_hitl} accion_esperada={esc.accion_esperada}"
    )


if __name__ == "__main__":
    from reclamos.observabilidad.otel import iniciar_registro
    iniciar_registro("seed_db")
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--caso-id", default=s.caso_id)
    ap.add_argument("--semilla", type=int, default=s.semilla)
    ap.add_argument("--tipo", default=None, help="fuerza el tipo de caso (la semilla sigue decidiendo el resto)")
    a = ap.parse_args()
    escenario = construir_escenario(a.caso_id, a.semilla, a.tipo)
    cargar(escenario)
    print(resumen(escenario))
