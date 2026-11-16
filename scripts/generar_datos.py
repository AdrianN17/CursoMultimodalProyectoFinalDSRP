"""Genera los artefactos de entrada del escenario: datos/constancia.png y datos/reporte.(wav|mp3) + .txt

Uso:  python scripts/generar_datos.py --caso-id C-07 --semilla 4213 [--tipo DUPLICADA]
Con PROVEEDOR_IA=azure el audio es voz real (TTS de Azure); con mock son tonos + transcripción de referencia.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from reclamos.config import get_settings  # noqa: E402
from reclamos.escenario import construir_escenario  # noqa: E402
from reclamos.escenario.artefactos import generar_artefactos  # noqa: E402
from reclamos.proveedores.interfaces import obtener_proveedor  # noqa: E402

if __name__ == "__main__":
    from reclamos.observabilidad.otel import iniciar_registro
    iniciar_registro("generar_datos")
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--caso-id", default=s.caso_id)
    ap.add_argument("--semilla", type=int, default=s.semilla)
    ap.add_argument("--tipo", default=None)
    ap.add_argument("--salida", default=str(RAIZ / "datos"))
    a = ap.parse_args()
    esc = construir_escenario(a.caso_id, a.semilla, a.tipo)
    rutas = generar_artefactos(esc, Path(a.salida), obtener_proveedor())
    print(f"CASO_ID={esc.caso_id} SEMILLA={esc.semilla} tipo={esc.tipo}")
    for k, v in rutas.items():
        print(f"  {k}: {v}")
    print(f"  relato: {esc.relato}")
