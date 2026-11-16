"""Genera docs/informe.pdf a partir de docs/informe.md (requiere `pip install markdown` y Microsoft Edge o Chrome).

Uso:  python scripts/generar_informe_pdf.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ORIGEN = RAIZ / "docs" / "informe.md"
DESTINO = RAIZ / "docs" / "informe.pdf"

NAVEGADORES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; line-height: 1.4; color: #1a1a1a; }
h1 { font-size: 19pt; border-bottom: 2px solid #1f4e79; padding-bottom: 4px; }
h2 { font-size: 13.5pt; color: #1f4e79; margin-top: 16px; break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9pt; break-inside: auto; }
tr { break-inside: avoid; }
th, td { border: 1px solid #9aa7b4; padding: 3px 6px; vertical-align: top; text-align: left; }
th { background: #e8eef4; }
code { font-family: Consolas, monospace; font-size: 8.8pt; background: #f2f2f2; padding: 0 2px; }
pre { background: #f5f5f5; border: 1px solid #ddd; padding: 6px; font-size: 8pt; white-space: pre-wrap; break-inside: avoid; }
pre code { background: none; }
blockquote { color: #555; border-left: 3px solid #ccc; margin-left: 0; padding-left: 10px; }
ul { margin: 4px 0; }
"""


def main() -> int:
    try:
        import markdown
    except ImportError:
        print("Falta el paquete 'markdown': pip install markdown", file=sys.stderr)
        return 1
    nav = next((n for n in NAVEGADORES if Path(n).exists()), None) or shutil.which("msedge") or shutil.which("chrome")
    if not nav:
        print("No se encontró Edge/Chrome para imprimir a PDF", file=sys.stderr)
        return 1
    cuerpo = markdown.markdown(ORIGEN.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "sane_lists"])
    cuerpo = re.sub(r'href="[^"]*\.md"', 'href="#"', cuerpo)
    html = f'<!doctype html><html lang="es"><meta charset="utf-8"><style>{CSS}</style><body>{cuerpo}</body></html>'
    with tempfile.TemporaryDirectory() as tmp:
        pagina = Path(tmp) / "informe.html"
        pagina.write_text(html, encoding="utf-8")
        cmd = [nav, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={tmp}",
               f"--print-to-pdf={DESTINO}", pagina.as_uri()]
        subprocess.run(cmd, check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    paginas = len(re.findall(rb"/Type\s*/Page[^s]", DESTINO.read_bytes()))
    print(f"{DESTINO.relative_to(RAIZ)} generado ({DESTINO.stat().st_size // 1024} KB, {paginas} páginas)")
    return 0 if os.path.exists(DESTINO) else 1


if __name__ == "__main__":
    raise SystemExit(main())
