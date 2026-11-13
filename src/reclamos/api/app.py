"""API REST (FastAPI + OpenAPI). Contrato: /docs y /openapi.json. Errores en application/problem+json (RFC 9457)."""
from __future__ import annotations

import hmac
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import db
from ..config import AGENTE_VERSION, RAIZ, get_settings
from ..hitl import aprobacion as hitl
from ..observabilidad.otel import configurar
from ..orquestador.nodos.salida import DIR_SALIDAS
from ..orquestador.servicio import ProcesadorReclamos, ServicioError

log = logging.getLogger("reclamos.api")
PREFIJO = "/api/v1"
UI_DIR = RAIZ / "ui"
EXT_IMAGEN = {".png", ".jpg", ".jpeg"}
EXT_AUDIO = {".wav", ".mp3", ".m4a", ".ogg", ".webm"}
_servicio: ProcesadorReclamos | None = None


def servicio() -> ProcesadorReclamos:
    global _servicio
    if _servicio is None:
        _servicio = ProcesadorReclamos()
    return _servicio


@asynccontextmanager
async def ciclo_vida(_: FastAPI):
    configurar()
    servicio()
    yield
    if _servicio:
        _servicio.cerrar()


app = FastAPI(title="Agente de reclamos bancarios multimodal", version=AGENTE_VERSION, lifespan=ciclo_vida,
              description="Recibe audio + constancia de pago, decide con políticas y herramientas MCP, "
                          "pide aprobación humana para acciones monetarias y responde solo en audio.")


# ----------------------------------------------------------------------------- errores problem+json
def problema(status: int, codigo: str, detalle: str, **extra) -> JSONResponse:
    cuerpo = {"type": f"urn:reclamos:error:{codigo}", "title": codigo, "status": status, "detail": detalle, **extra}
    return JSONResponse(cuerpo, status_code=status, media_type="application/problem+json")


@app.exception_handler(ServicioError)
async def _h_servicio(_: Request, e: ServicioError):
    return problema(404 if "INEXISTENTE" in e.codigo else 409, e.codigo, e.mensaje)


@app.exception_handler(hitl.HitlError)
async def _h_hitl(_: Request, e: hitl.HitlError):
    estado = {"NO_EXISTE": 404, "ROL_INSUFICIENTE": 403, "DECISION_INVALIDA": 422}.get(e.codigo, 409)
    return problema(estado, e.codigo, e.mensaje)


@app.exception_handler(RequestValidationError)
async def _h_validacion(_: Request, e: RequestValidationError):
    return problema(422, "VALIDACION", "La solicitud no cumple el contrato", errores=json.loads(json.dumps(
        e.errors(), default=str)))


@app.exception_handler(HTTPException)
async def _h_http(_: Request, e: HTTPException):
    return problema(e.status_code, "HTTP_%d" % e.status_code, str(e.detail))


@app.exception_handler(Exception)
async def _h_generico(_: Request, e: Exception):
    log.exception("error no controlado")
    return problema(500, "ERROR_INTERNO", "Error interno; el equipo fue notificado")


def exigir_analista(x_analista_key: str | None = Header(default=None)) -> None:
    esperado = os.environ.get("ANALISTA_API_KEY", "demo-analista")
    if not x_analista_key or not hmac.compare_digest(x_analista_key, esperado):
        raise HTTPException(401, "Falta o es inválida la cabecera X-Analista-Key")


# ----------------------------------------------------------------------------- modelos
class SesionIn(BaseModel):
    caso_id: str | None = Field(default=None, examples=["C-07"])
    semilla: int | None = Field(default=None, examples=[4213])


class DecisionIn(BaseModel):
    decision: Literal["APROBADA", "RECHAZADA"]
    motivo: str = Field(min_length=3, max_length=300)
    aprobador: str = Field(min_length=2, max_length=60)
    rol: Literal["ANALISTA", "SUPERVISOR"] = "ANALISTA"


# ----------------------------------------------------------------------------- utilidades
async def guardar_subida(f: UploadFile, permitidas: set[str], tipo: str) -> Path:
    ext = Path(f.filename or "").suffix.lower()
    if ext not in permitidas:
        raise HTTPException(415, f"Formato de {tipo} no admitido: {ext or 'sin extensión'}")
    carpeta = get_settings().evidencia_dir / "subidas"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{uuid.uuid4().hex}{ext}"
    limite, total = get_settings().max_upload_mb * 1024 * 1024, 0
    with destino.open("wb") as out:
        while trozo := await f.read(1024 * 256):
            total += len(trozo)
            if total > limite:
                out.close()
                destino.unlink(missing_ok=True)
                raise HTTPException(413, f"El {tipo} supera {get_settings().max_upload_mb} MB")
            out.write(trozo)
    return destino


def _publico(res: dict) -> dict:
    audio = res.get("audio_path")
    s = get_settings()
    out = {k: res.get(k) for k in ("sesion_id", "ticket_id", "trace_id", "latencia_total_ms", "pendiente_hitl",
                                  "aprobacion_id", "respuesta")}
    out["audio_url"] = f"{PREFIJO}/audio/{Path(audio).name}" if audio else None
    out["error"] = res.get("error") if s.demo_mode else None
    return out


# ----------------------------------------------------------------------------- rutas
@app.get(f"{PREFIJO}/health", tags=["operación"])
def health():
    try:
        db.uno("SELECT 1 AS ok")
        base = "ok"
    except Exception:
        base = "caída"
    return {"estado": "ok" if base == "ok" else "degradado", "base_de_datos": base, "version": AGENTE_VERSION,
            "proveedor_ia": get_settings().proveedor}


@app.post(f"{PREFIJO}/sesiones", status_code=201, tags=["reclamos"],
          summary="Inicia sesión y emite el OTP (el canal real lo enviaría por SMS/correo)")
def crear_sesion(body: SesionIn | None = None):
    b = body or SesionIn()
    ses = servicio().iniciar_sesion(b.caso_id, b.semilla)
    if not get_settings().demo_mode:
        ses.pop("otp_demo", None)
    return ses


@app.post(f"{PREFIJO}/reclamos", tags=["reclamos"], summary="Envía un turno: audio y/o imagen y/o texto + OTP")
async def crear_reclamo(sesion_id: str = Form(...), otp: str | None = Form(default=None),
                        texto: str | None = Form(default=None), audio: UploadFile | None = File(default=None),
                        imagen: UploadFile | None = File(default=None),
                        idempotency_key: str | None = Header(default=None)):
    a = await guardar_subida(audio, EXT_AUDIO, "audio") if audio and audio.filename else None
    i = await guardar_subida(imagen, EXT_IMAGEN, "imagen") if imagen and imagen.filename else None
    from starlette.concurrency import run_in_threadpool
    res = await run_in_threadpool(servicio().procesar, sesion_id, texto, a, i, otp, idempotency_key)
    return _publico(res)


@app.get(f"{PREFIJO}/reclamos/{{ticket_id}}", tags=["reclamos"])
def estado_reclamo(ticket_id: str):
    t = db.uno("SELECT ticket_id, estado, resolucion, tipo_reclamo, accion_ejecutada, creado_en, actualizado_en "
               "FROM Ticket WHERE ticket_id = ?", (ticket_id,))
    if not t:
        raise HTTPException(404, f"No existe el ticket {ticket_id}")
    t["eventos"] = db.consultar("SELECT tipo, actor, ts FROM TicketEvento WHERE ticket_id = ? ORDER BY evento_id",
                                (ticket_id,))
    return t


@app.get(f"{PREFIJO}/audio/{{nombre}}", tags=["reclamos"], response_class=FileResponse)
def descargar_audio(nombre: str):
    ruta = (DIR_SALIDAS / Path(nombre).name).resolve()
    if ruta.parent != DIR_SALIDAS.resolve() or not ruta.is_file():
        raise HTTPException(404, "Audio no encontrado")
    return FileResponse(ruta)


@app.get(f"{PREFIJO}/aprobaciones", tags=["analista"], dependencies=[Depends(exigir_analista)])
def listar_aprobaciones(estado: str | None = "PENDIENTE"):
    filas = hitl.listar(estado)
    for f in filas:
        f["resumen"] = json.loads(f.pop("resumen_json") or "{}")
    return filas


@app.post(f"{PREFIJO}/aprobaciones/{{aprobacion_id}}/decision", tags=["analista"],
          dependencies=[Depends(exigir_analista)], summary="Decide y reanuda el flujo desde el checkpoint")
def decidir(aprobacion_id: str, d: DecisionIn):
    return _publico(servicio().resolver_hitl(aprobacion_id, d.decision, d.motivo, d.aprobador, d.rol))


@app.post(f"{PREFIJO}/aprobaciones/expirar", tags=["analista"], dependencies=[Depends(exigir_analista)])
def expirar():
    return [_publico(r) for r in servicio().expirar_pendientes()]


if UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
