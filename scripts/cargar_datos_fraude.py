"""Carga db/datos_prueba_fraude_otp.sql (operaciones con y sin OTP para probar la política P-11).

Uso:  python scripts/cargar_datos_fraude.py     (ejecútelo DESPUÉS de scripts/seed_db.py, que borra los datos de negocio)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from reclamos import db  # noqa: E402

ARCHIVO = RAIZ / "db" / "datos_prueba_fraude_otp.sql"


def sentencias(sql: str) -> list[str]:
    sin_comentarios = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    return [s.strip() for s in re.split(r";\s*(?:\r?\n|$)", sin_comentarios) if s.strip()]


if __name__ == "__main__":
    with db.conexion(autocommit=True) as cn:
        for s in sentencias(ARCHIVO.read_text(encoding="utf-8")):
            cur = cn.cursor()
            cur.execute(s)
            if cur.description:
                for f in cur.fetchall():
                    print(" | ".join(str(x) for x in f))
    print("Datos de fraude OTP cargados (CLI-9001, CLI-9002, CLI-9003).")
