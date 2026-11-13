"""Resume métricas operativas desde evidencia/trazas.jsonl: latencia p50/p95, errores, aprobaciones y costo de LLM.

Uso:  python scripts/resumen_metricas.py [--archivo evidencia/trazas.jsonl] [--salida evidencia/resumen_metricas.md]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))


def percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    v = sorted(valores)
    k = (len(v) - 1) * p
    i, f = int(k), k - int(k)
    return v[i] if i + 1 >= len(v) else v[i] + (v[i + 1] - v[i]) * f


def resumir(spans: list[dict]) -> str:
    raiz = [s for s in spans if s["name"] == "reclamo.procesar"]
    lat = [s["duracion_ms"] for s in raiz]
    resultados = Counter(s["atributos"].get("reclamo.resultado", "?") for s in raiz)
    errores = sum(1 for s in raiz if s["estado"] == "ERROR" or s["atributos"].get("reclamo.resultado") == "ERROR_TECNICO")
    hitl = sum(1 for s in raiz if s["atributos"].get("reclamo.hitl_pendiente"))
    tokens_in = sum(s["atributos"].get("llm.tokens_in", 0) for s in spans)
    tokens_out = sum(s["atributos"].get("llm.tokens_out", 0) for s in spans)
    costo = sum(s["atributos"].get("llm.costo_estimado_usd", 0.0) for s in spans)
    por_etapa: dict[str, list[float]] = defaultdict(list)
    for s in spans:
        por_etapa[s["name"]].append(s["duracion_ms"])
    reanudados = [s for s in spans if s["name"] == "reclamo.reanudar_hitl"]

    n = len(raiz) or 1
    out = ["# Resumen de métricas", "",
           f"- Ejecuciones (`reclamo.procesar`): **{len(raiz)}**; reanudaciones HITL: **{len(reanudados)}**",
           f"- Latencia extremo a extremo: p50 **{percentil(lat, .5):.0f} ms**, p95 **{percentil(lat, .95):.0f} ms**"
           f" (media {statistics.mean(lat) if lat else 0:.0f} ms)",
           f"- Tasa de error técnico: **{errores / n:.1%}**",
           f"- Enviadas a aprobación humana: **{hitl / n:.1%}**",
           f"- Tokens LLM: entrada **{tokens_in}**, salida **{tokens_out}**; costo estimado **USD {costo:.4f}**"
           f" (USD {costo / n:.4f} por ejecución)", "", "## Resultados", "", "| resultado | n |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in resultados.most_common()]
    out += ["", "## Latencia por etapa (ms)", "", "| etapa | n | p50 | p95 |", "|---|---|---|---|"]
    for nombre, v in sorted(por_etapa.items(), key=lambda kv: -percentil(kv[1], .95)):
        out.append(f"| {nombre} | {len(v)} | {percentil(v, .5):.1f} | {percentil(v, .95):.1f} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    from reclamos.config import get_settings
    ev = get_settings().evidencia_dir
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archivo", default=str(ev / "trazas.jsonl"))
    ap.add_argument("--salida", default=str(ev / "resumen_metricas.md"))
    a = ap.parse_args()
    ruta = Path(a.archivo)
    if not ruta.exists():
        sys.exit(f"No existe {ruta}; ejecute primero el flujo (main.py o las pruebas).")
    spans = [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]
    md = resumir(spans)
    Path(a.salida).write_text(md, encoding="utf-8")
    print(md)
