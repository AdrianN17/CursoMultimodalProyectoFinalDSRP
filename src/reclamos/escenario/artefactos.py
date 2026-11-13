"""Generadores de artefactos sintéticos reproducibles (constancia PNG y audio del relato) a partir del escenario."""
from __future__ import annotations

import json
import random
import struct
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from .escenario import Escenario


def _fuente(tam: int):
    try:
        return ImageFont.load_default(size=tam)
    except TypeError:  # Pillow antiguo
        return ImageFont.load_default()


def lineas_constancia(c: dict) -> list[str]:
    return [
        c["titulo"],
        f"Fecha: {c['fecha']}   Hora: {c['hora']}",
        f"Cuenta de cargo: {c['cuenta_producto']}",
        c["tarjeta_mascara"],
        f"Empresa: {c['empresa']}",
        f"Servicio: {c['servicio']}",
        f"Nombre: {c['nombre']}",
        f"Código de operación : {c['codigo_operacion']}",
        f"Monto : {c['monto_texto']}",
    ]


def generar_constancia_png(constancia: dict, destino: Path) -> Path:
    """Dibuja la constancia con el formato oficial y embebe los campos en metadatos (los usa el visor MOCK)."""
    img = Image.new("RGB", (640, 520), "white")
    d = ImageDraw.Draw(img)
    titulo, normal = _fuente(30), _fuente(23)
    y = 30
    for i, linea in enumerate(lineas_constancia(constancia)):
        d.text((40, y), linea, fill="black", font=titulo if i == 0 else normal)
        y += 60 if i == 0 else 50
    info = PngInfo()
    info.add_text("constancia_json", json.dumps(constancia, ensure_ascii=False))
    destino.parent.mkdir(parents=True, exist_ok=True)
    img.save(destino, "PNG", pnginfo=info)
    return destino


def generar_imagen_no_constancia(destino: Path, semilla: int = 0) -> Path:
    """Imagen válida pero que NO es una constancia (prueba adversarial)."""
    rng = random.Random(semilla)
    img = Image.new("RGB", (400, 400), (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)))
    d = ImageDraw.Draw(img)
    for _ in range(12):
        x0, y0 = rng.randint(0, 250), rng.randint(0, 250)
        d.rectangle([x0, y0, x0 + rng.randint(20, 150), y0 + rng.randint(20, 150)], outline="white", width=3)
    destino.parent.mkdir(parents=True, exist_ok=True)
    img.save(destino, "PNG")
    return destino


def generar_audio_ruido(destino: Path, semilla: int = 0, segundos: float = 1.5) -> Path:
    """WAV de ruido blanco sin transcripción asociada (audio ininteligible)."""
    rng = random.Random(semilla)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", rng.randint(-3000, 3000)) for _ in range(int(16000 * segundos))))
    return destino


def generar_audio_relato(relato: str, destino_sin_ext: Path, proveedor) -> Path:
    """TTS del relato del cliente (voz real con Azure; tonos con MOCK) + transcripción de referencia (.txt)."""
    destino_sin_ext.parent.mkdir(parents=True, exist_ok=True)
    ruta = proveedor.sintetizar(relato, destino_sin_ext)
    ruta.with_suffix(".txt").write_text(relato, encoding="utf-8")
    return ruta


def generar_artefactos(esc: Escenario, carpeta: Path, proveedor) -> dict[str, Path | None]:
    carpeta.mkdir(parents=True, exist_ok=True)
    return {
        "audio": generar_audio_relato(esc.relato, carpeta / "reporte", proveedor),
        "imagen": generar_constancia_png(esc.constancia, carpeta / "constancia.png") if esc.constancia else None,
    }
