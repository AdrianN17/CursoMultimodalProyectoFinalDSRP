"""Indexa las políticas (rag/politicas_reclamacion.md) en Qdrant. Idempotente por versión del documento.

Uso:  python scripts/ingestar_politicas.py [--forzar]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from reclamos.proveedores.interfaces import obtener_proveedor  # noqa: E402
from reclamos.rag.ingesta import indexar  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--forzar", action="store_true", help="reindexa aunque la versión ya esté cargada")
    n = indexar(obtener_proveedor(), forzar=ap.parse_args().forzar)
    print(f"Fragmentos indexados: {n}")
