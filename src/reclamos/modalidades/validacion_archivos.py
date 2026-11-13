"""Validación de archivos subidos (antes de que lleguen a cualquier modelo)."""
from __future__ import annotations

import wave
from pathlib import Path

from PIL import Image, UnidentifiedImageError

EXT_IMAGEN = {".jpg", ".jpeg", ".png"}
EXT_AUDIO = {".wav", ".mp3", ".m4a", ".webm", ".ogg"}
EXT_VIDEO = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv"}


class ArchivoInvalido(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(f"{codigo}: {mensaje}")
        self.codigo = codigo
        self.mensaje = mensaje


def _base(ruta: Path, permitidas: set[str], max_mb: int, tipo: str) -> bytes:
    if not ruta.exists() or not ruta.is_file():
        raise ArchivoInvalido("ARCHIVO_INEXISTENTE", f"No existe el archivo de {tipo}")
    ext = ruta.suffix.lower()
    if ext in EXT_VIDEO:
        raise ArchivoInvalido("VIDEO_NO_PERMITIDO", "No se aceptan videos; envíe una imagen")
    if ext not in permitidas:
        raise ArchivoInvalido("EXTENSION_NO_PERMITIDA", f"Extensión {ext or '(ninguna)'} no permitida para {tipo}")
    tam = ruta.stat().st_size
    if tam == 0:
        raise ArchivoInvalido("ARCHIVO_VACIO", f"El archivo de {tipo} está vacío")
    if tam > max_mb * 1024 * 1024:
        raise ArchivoInvalido("ARCHIVO_MUY_GRANDE", f"El archivo de {tipo} supera {max_mb} MB")
    with ruta.open("rb") as f:
        return f.read(16)


def validar_imagen(ruta: Path, max_mb: int = 5) -> Path:
    cabecera = _base(ruta, EXT_IMAGEN, max_mb, "imagen")
    es_png = cabecera.startswith(b"\x89PNG\r\n\x1a\n")
    es_jpg = cabecera.startswith(b"\xff\xd8\xff")
    if not (es_png or es_jpg):
        raise ArchivoInvalido("CONTENIDO_NO_ES_IMAGEN", "El contenido real no es PNG/JPEG (firma inválida)")
    try:
        with Image.open(ruta) as im:
            im.verify()
        with Image.open(ruta) as im:
            ancho, alto = im.size
    except (UnidentifiedImageError, OSError) as exc:
        raise ArchivoInvalido("IMAGEN_CORRUPTA", f"No se puede decodificar la imagen: {exc}") from exc
    if ancho < 200 or alto < 200:
        raise ArchivoInvalido("IMAGEN_MUY_PEQUENA", f"Resolución {ancho}x{alto} insuficiente (mín. 200x200)")
    return ruta


def validar_audio(ruta: Path, max_mb: int = 5) -> Path:
    c = _base(ruta, EXT_AUDIO, max_mb, "audio")
    firmas = (
        c.startswith(b"RIFF") and c[8:12] == b"WAVE",
        c.startswith(b"ID3") or c[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
        c[4:8] == b"ftyp",
        c.startswith(b"\x1aE\xdf\xa3"),
        c.startswith(b"OggS"),
    )
    if not any(firmas):
        raise ArchivoInvalido("CONTENIDO_NO_ES_AUDIO", "El contenido real no es un audio soportado (firma inválida)")
    if ruta.suffix.lower() == ".wav":
        try:
            with wave.open(str(ruta), "rb") as w:
                segundos = w.getnframes() / float(w.getframerate() or 1)
        except (wave.Error, EOFError) as exc:
            raise ArchivoInvalido("AUDIO_CORRUPTO", f"WAV ilegible: {exc}") from exc
        if segundos < 0.3:
            raise ArchivoInvalido("AUDIO_MUY_CORTO", "El audio dura menos de 0.3 s")
    return ruta
