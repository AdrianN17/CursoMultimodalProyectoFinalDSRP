"""OpenTelemetry: trazas, métricas y logs correlacionados.

- Un span por nodo/tool/llamada a modelo; `trace_id` único por ejecución.
- Exporta SIEMPRE a evidencia/trazas.jsonl (+ logs.jsonl y metricas.jsonl) y, si OTEL_EXPORTER_OTLP_ENDPOINT
  está definido, también por OTLP (collector/Jaeger).
- `caso.id` y `caso.semilla` van en cada span y en cada log.
- Cada ejecución (script, API, pruebas) escribe además un log detallado paso a paso en
  temporal/<proceso>_<fecha-hora>.log (ver `iniciar_registro`); los subprocesos (servidor MCP, hitl_cli) añaden al mismo fichero.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Span, Status, StatusCode

from ..config import AGENTE_VERSION, get_settings
from ..seguridad.sanitizar_pii import enmascarar_texto, sanitizar

LOGGER = logging.getLogger("reclamos")
LOG_TRAZA = logging.getLogger("reclamos.traza")
_PROFUNDIDAD: contextvars.ContextVar[int] = contextvars.ContextVar("prof_span", default=0)
_CTX_CASO: contextvars.ContextVar[tuple[str, int] | None] = contextvars.ContextVar("ctx_caso", default=None)
_LOCK = threading.Lock()
_ESTADO: dict[str, Any] = {"listo": False, "meter_provider": None, "instrumentos": None, "registro": False,
                           "handlers": False}


def fijar_caso(caso_id: str, semilla: int) -> None:
    _CTX_CASO.set((caso_id, semilla))


def caso_actual() -> tuple[str, int]:
    v = _CTX_CASO.get()
    if v:
        return v
    s = get_settings()
    return s.caso_id, s.semilla


class _JsonlSpanExporter(SpanExporter):
    def __init__(self, ruta: Path):
        self._ruta = ruta
        ruta.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Any) -> SpanExportResult:
        with _LOCK, self._ruta.open("a", encoding="utf-8") as f:
            for s in spans:
                f.write(json.dumps(_span_a_dict(s), ensure_ascii=False, default=str) + "\n")
        return SpanExportResult.SUCCESS


def _span_a_dict(s: ReadableSpan) -> dict[str, Any]:
    ctx = s.get_span_context()
    return {
        "trace_id": f"{ctx.trace_id:032x}",
        "span_id": f"{ctx.span_id:016x}",
        "parent_id": f"{s.parent.span_id:016x}" if s.parent else None,
        "name": s.name,
        "inicio": datetime.fromtimestamp(s.start_time / 1e9, timezone.utc).isoformat(),
        "duracion_ms": round((s.end_time - s.start_time) / 1e6, 3),
        "estado": s.status.status_code.name,
        "atributos": dict(s.attributes or {}),
        "eventos": [{"nombre": e.name, "atributos": dict(e.attributes or {})} for e in s.events],
    }


class _FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ctx = trace.get_current_span().get_span_context()
        caso, semilla = caso_actual()
        d = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": enmascarar_texto(record.getMessage()),
            "caso.id": caso,
            "caso.semilla": semilla,
            "trace_id": f"{ctx.trace_id:032x}" if ctx.is_valid else None,
            "span_id": f"{ctx.span_id:016x}" if ctx.is_valid else None,
        }
        if record.exc_info:
            d["excepcion"] = enmascarar_texto(self.formatException(record.exc_info))
        return json.dumps(d, ensure_ascii=False)


class _FormatoConsola(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ctx = trace.get_current_span().get_span_context()
        caso, semilla = caso_actual()
        tid = f"{ctx.trace_id:032x}"[:8] if ctx.is_valid else "--------"
        return f"[{caso}/{semilla} t={tid}] {record.levelname:<7} {enmascarar_texto(record.getMessage())}"


class _FormatoArchivo(logging.Formatter):
    """Línea legible para seguir la ejecución paso a paso (hora local, caso, traza, proceso, nivel y módulo)."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = trace.get_current_span().get_span_context()
        caso, semilla = caso_actual()
        tid = f"{ctx.trace_id:032x}"[:8] if ctx.is_valid else "--------"
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        linea = (f"{ts} [{caso}/{semilla} t={tid} p={record.process}] {record.levelname:<7} "
                 f"{record.name.removeprefix('reclamos.')}: {enmascarar_texto(record.getMessage())}")
        if record.exc_info:
            linea += "\n" + enmascarar_texto(self.formatException(record.exc_info))
        return linea


def _nombre_proceso() -> str:
    arg0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else Path("")
    nombre = arg0.stem
    if nombre in ("", "__main__", "-c", "-m"):  # python -m pytest -> .../pytest/__main__.py
        nombre = arg0.parent.name
    return re.sub(r"[^\w.-]", "_", nombre) or "python"


def ruta_registro() -> Path | None:
    """Ruta del log de esta ejecución (None si aún no se inició)."""
    r = os.environ.get("REGISTRO_ARCHIVO")
    return Path(r) if r else None


def iniciar_registro(nombre: str | None = None) -> Path:
    """Abre (una vez por proceso) temporal/<nombre>_<AAAA-MM-DD_HH-MM-SS>.log con TODO el detalle (nivel DEBUG):
    cada span (nodo, tool, LLM, RAG, STT/TTS), consultas SQL, llamadas HTTP y errores con traza.
    La ruta se publica en REGISTRO_ARCHIVO: el servidor MCP y otros subprocesos añaden al mismo fichero."""
    with _LOCK:
        if _ESTADO["registro"]:
            return Path(os.environ["REGISTRO_ARCHIVO"])
        ruta_env = os.environ.get("REGISTRO_ARCHIVO")
        if ruta_env:
            ruta = Path(ruta_env)
        else:
            marca = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            ruta = get_settings().temporal_dir / f"{nombre or _nombre_proceso()}_{marca}.log"
            os.environ["REGISTRO_ARCHIVO"] = str(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(ruta, encoding="utf-8")
        h.setLevel(logging.DEBUG)
        h.setFormatter(_FormatoArchivo())
        LOGGER.setLevel(logging.DEBUG)
        LOGGER.propagate = False
        LOGGER.addHandler(h)
        http = logging.getLogger("httpx")  # llamadas a Azure OpenAI / Speech / Qdrant (sin cabeceras ni claves)
        http.setLevel(logging.INFO)
        http.propagate = False
        http.addHandler(h)
        _ESTADO["registro"] = True
    LOGGER.info("registro iniciado: %s (pid=%s) argv=%s", ruta.name, os.getpid(), " ".join(sys.argv)[:200])
    return ruta


def configurar(servicio: str = "agente-reclamos", consola: bool = True) -> None:
    """Idempotente. Seguro de llamar desde API, CLI, pruebas y servidor MCP (que escribe SOLO en stderr)."""
    with _LOCK:
        if _ESTADO["listo"]:
            return
        _ESTADO["listo"] = True
    s = get_settings()
    s.evidencia_dir.mkdir(parents=True, exist_ok=True)
    recurso = Resource.create({
        "service.name": servicio, "agente.version": AGENTE_VERSION,
        "caso.id": s.caso_id, "caso.semilla": s.semilla,
    })

    tp = TracerProvider(resource=recurso)
    tp.add_span_processor(SimpleSpanProcessor(_JsonlSpanExporter(s.evidencia_dir / "trazas.jsonl")))
    if s.otel_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=s.otel_endpoint, insecure=True)))
        except Exception as exc:  # el exportador OTLP es opcional
            print(f"[otel] OTLP trazas deshabilitado: {exc}", file=sys.stderr)
    trace.set_tracer_provider(tp)

    fh = (s.evidencia_dir / "metricas.jsonl").open("a", encoding="utf-8")
    lector = PeriodicExportingMetricReader(
        ConsoleMetricExporter(out=fh, formatter=lambda md: md.to_json(indent=None) + "\n"),
        export_interval_millis=60_000,
    )
    lectores = [lector]
    if s.otel_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
            lectores.append(PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=s.otel_endpoint, insecure=True)))
        except Exception as exc:
            print(f"[otel] OTLP métricas deshabilitado: {exc}", file=sys.stderr)
    mp = MeterProvider(resource=recurso, metric_readers=lectores)
    metrics.set_meter_provider(mp)
    _ESTADO["meter_provider"] = mp

    iniciar_registro()
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.propagate = False
    if not _ESTADO["handlers"]:
        _ESTADO["handlers"] = True
        archivo = logging.FileHandler(s.evidencia_dir / "logs.jsonl", encoding="utf-8")
        archivo.setLevel(logging.INFO)
        archivo.setFormatter(_FormatoJson())
        LOGGER.addHandler(archivo)
        if consola:
            c = logging.StreamHandler(sys.stderr)
            c.setLevel(logging.INFO)
            c.setFormatter(_FormatoConsola())
            LOGGER.addHandler(c)


def volcar_metricas() -> None:
    mp = _ESTADO.get("meter_provider")
    if mp is not None:
        mp.force_flush()


def _instrumentos() -> dict[str, Any]:
    if _ESTADO["instrumentos"] is None:
        m = metrics.get_meter("reclamos")
        _ESTADO["instrumentos"] = {
            "latencia": m.create_histogram("latencia_etapa_ms", unit="ms", description="Latencia por etapa"),
            "reclamos": m.create_counter("reclamos_total", description="Reclamos procesados por resultado"),
            "errores": m.create_counter("errores_total", description="Errores por nodo/tipo"),
            "hitl": m.create_counter("hitl_decisiones_total", description="Decisiones HITL"),
            "tokens": m.create_counter("llm_tokens_total", description="Tokens por dirección"),
            "costo": m.create_counter("llm_costo_usd_total", unit="USD", description="Costo estimado"),
        }
    return _ESTADO["instrumentos"]


def metrica(nombre: str, valor: float, **atributos: Any) -> None:
    inst = _instrumentos()[nombre]
    if nombre == "latencia":
        inst.record(valor, atributos)
    else:
        inst.add(valor, atributos)


@contextmanager
def trazar(nombre: str, **atributos: Any) -> Iterator[Span]:
    """Span con caso/semilla, atributos sanitizados, excepción registrada y métrica de latencia."""
    configurar()
    caso, semilla = caso_actual()
    tracer = trace.get_tracer("reclamos")
    t0 = time.perf_counter()
    prof = _PROFUNDIDAD.get()
    marca = _PROFUNDIDAD.set(prof + 1)
    sangria = "  " * prof
    LOG_TRAZA.debug("%s-> %s", sangria, nombre)
    with tracer.start_as_current_span(nombre) as span:
        span.set_attribute("caso.id", caso)
        span.set_attribute("caso.semilla", semilla)
        span.set_attribute("agente.version", AGENTE_VERSION)
        for k, v in atributos.items():
            poner_atributo(span, k, v)
        try:
            yield span
        except BaseException as exc:
            if type(exc).__name__ == "GraphInterrupt":
                LOG_TRAZA.debug("%s|| %s interrumpido: espera de aprobación humana", sangria, nombre)
            else:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
                span.set_attribute("error.tipo", type(exc).__name__)
                LOG_TRAZA.debug("%s!! %s falló: %s: %s", sangria, nombre, type(exc).__name__, str(exc)[:200])
            raise
        finally:
            ms = (time.perf_counter() - t0) * 1000
            metrica("latencia", ms, etapa=nombre)
            LOG_TRAZA.debug("%s<- %s %.1f ms", sangria, nombre, ms)
            try:
                _PROFUNDIDAD.reset(marca)
            except ValueError:  # el span terminó en otro contexto (hilo): la sangría es solo cosmética
                pass


def poner_atributo(span: Span, clave: str, valor: Any) -> None:
    if valor is None:
        return
    if isinstance(valor, (dict, list, tuple)):
        valor = json.dumps(sanitizar(valor), ensure_ascii=False, default=str)[:2000]
    elif isinstance(valor, str):
        valor = enmascarar_texto(valor)[:2000]
    elif not isinstance(valor, (bool, int, float)):
        valor = str(valor)
    span.set_attribute(clave, valor)


def registrar_uso_llm(span: Span, modelo: str, tokens_in: int, tokens_out: int) -> float:
    s = get_settings()
    costo = tokens_in / 1000 * s.precio_in_1k + tokens_out / 1000 * s.precio_out_1k
    span.set_attribute("llm.modelo", modelo)
    span.set_attribute("llm.tokens_in", tokens_in)
    span.set_attribute("llm.tokens_out", tokens_out)
    span.set_attribute("llm.costo_estimado_usd", round(costo, 6))
    metrica("tokens", tokens_in, direccion="in")
    metrica("tokens", tokens_out, direccion="out")
    metrica("costo", costo)
    return costo


def trace_id_actual() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return f"{ctx.trace_id:032x}" if ctx.is_valid else None
