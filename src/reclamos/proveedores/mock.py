"""Proveedor MOCK determinístico: permite ejecutar/probar TODO el flujo sin credenciales de Azure.

No es una simulación de calidad de modelo: aplica reglas simples para que las pruebas del grafo, tools, HITL
y observabilidad sean reproducibles. En producción se usa ProveedorAzure (PROVEEDOR_IA=azure).
- STT: lee `<audio>.txt` junto al archivo (transcripción 'verdad de terreno'); sin sidecar = audio ininteligible.
- Visión: lee los metadatos PNG que escribe scripts/generar_constancia.py; una imagen sin ellos no es constancia.
- TTS: genera un WAV con tonos (duración proporcional al texto).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import wave
from pathlib import Path

from PIL import Image

from .interfaces import ProveedorIA, Uso

_MONTO = re.compile(r"(?:S/|US\$|\$)\s*([\d.,]+)")
_CODIGO = re.compile(r"(?:c[oó]digo de operaci[oó]n|operaci[oó]n)\D{0,5}(\d{6,8})", re.I)


def _a_float(txt: str) -> float | None:
    try:
        return float(txt.replace(",", ""))
    except ValueError:
        return None


class ProveedorMock(ProveedorIA):
    nombre = "mock"
    extension_audio = ".wav"

    def _chat_json(self, tarea, system, payload, modelo):
        usado = "mock-router" if modelo == "router" else "mock-chat"
        salida = self._clasificar(payload) if tarea == "clasificar_intencion" else self._analizar(payload)
        return salida, Uso(len(json.dumps(payload)) // 4, len(json.dumps(salida)) // 4), usado

    # ---- clasificación de intención (router barato) -------------------------------------------
    def _clasificar(self, p: dict) -> dict:
        t = (p.get("texto") or "").lower()
        if re.search(r"c[oó]mo va|estado de mi (reclamo|ticket)|seguimiento|en qu[eé] est[aá]", t):
            intencion = "CONSULTA_ESTADO"
        elif re.search(r"dos veces|duplic|doble|repetid", t):
            intencion = "DUPLICADO"
        elif re.search(r"no reconozco|no autoric|sin mi (consentimiento|autorizaci)|no fui yo", t):
            intencion = "SIN_CONSENTIMIENTO"
        elif re.search(r"incorrect|equivocad|importe|monto", t):
            intencion = "MONTO_INCORRECTO"
        else:
            intencion = "OTRO"
        m = _MONTO.search(p.get("texto") or "")
        c = _CODIGO.search(p.get("texto") or "")
        return {
            "intencion": intencion,
            "moneda_mencionada": "USD" if re.search(r"d[oó]lar|usd|us\$", t) else ("PEN" if m else None),
            "monto_mencionado": _a_float(m.group(1)) if m else None,
            "codigo_operacion_mencionado": c.group(1) if c else None,
            "intento_manipulacion": bool(re.search(r"ignora|olvida.*(reglas|pol[ií]ticas)|reembols[ao] .*sin", t)),
        }

    # ---- análisis del agente (razonamiento sobre evidencias) ------------------------------------
    def _analizar(self, p: dict) -> dict:
        const, maestro = p.get("constancia"), p.get("maestro")
        intencion = (p.get("intencion") or {}).get("intencion", "OTRO")
        usadas = [("audio" if p.get("origen_relato") == "audio" else "texto")]
        comp = {"monto_relato": (p.get("intencion") or {}).get("monto_mencionado"),
                "monto_imagen": const.get("monto") if const else None,
                "monto_bd": maestro.get("monto") if maestro else None, "coincide": None}
        out = {"inferencia": "OTRO", "evidencias_usadas": usadas, "comparacion": comp, "discrepancias": [],
               "politicas_aplicables": [], "accion_propuesta": "ESCALAR_OPERADOR", "confianza": 0.6,
               "requiere_hitl": False, "explicacion": ""}
        if not const:
            out.update(inferencia="SIN_EVIDENCIA", accion_propuesta="PEDIR_INFO", politicas_aplicables=["P-02"],
                       explicacion="No hay constancia de pago válida; sin evidencia no se puede reclamar.")
            return out
        usadas.append("imagen")
        if not maestro:
            out.update(explicacion="La operación de la constancia no existe en la base de datos.", confianza=0.5)
            return out
        usadas += ["bd", "politica"]
        if not maestro.get("pertenece_al_cliente", False):
            out.update(inferencia="OPERACION_AJENA", accion_propuesta="RECHAZAR", politicas_aplicables=["P-04"],
                       confianza=0.95, explicacion="La operación pertenece a otro cliente.")
            return out
        coincide = abs((comp["monto_imagen"] or 0) - (comp["monto_bd"] or 0)) < 0.005
        comp["coincide"] = coincide
        if not coincide:
            out["discrepancias"].append({"campo": "monto", "percibido": str(comp["monto_imagen"]),
                                         "maestro": str(comp["monto_bd"])})
            out.update(inferencia="MONTO_INCORRECTO", accion_propuesta="ESCALAR_OPERADOR", confianza=0.9,
                       explicacion="El monto de la constancia no coincide con el registrado en BD; se escala.")
            return out
        duplicados = [d for d in p.get("duplicados", []) if not d.get("anulada")]
        if intencion == "DUPLICADO" and len(duplicados) >= 2:
            out["inferencia"] = "COBRO_DUPLICADO"
        elif intencion == "SIN_CONSENTIMIENTO":
            out["inferencia"] = "SIN_CONSENTIMIENTO"
        else:
            out.update(explicacion="No se pudo clasificar el motivo del reclamo con seguridad.")
            return out
        if not maestro.get("tarjeta_habilitada", True):
            out.update(accion_propuesta="ESCALAR_OPERADOR", politicas_aplicables=["P-06"], confianza=0.9,
                       explicacion="La tarjeta está deshabilitada; un operador coordina el medio de reembolso.")
        elif intencion == "SIN_CONSENTIMIENTO" and maestro.get("autenticada_otp", True):
            out.update(accion_propuesta="ESCALAR_OPERADOR", politicas_aplicables=["P-11"], confianza=0.9,
                       explicacion="La operación fue validada con OTP del cliente; posible ingeniería social, "
                                   "se escala a un operador.")
        else:
            accion = "REEMBOLSO" if maestro.get("facturada") else "ANULACION"
            out.update(accion_propuesta=accion, requiere_hitl=True, confianza=0.85,
                       politicas_aplicables=["P-01"] + (["P-03"] if accion == "ANULACION" else []),
                       explicacion=f"Reclamo válido ({out['inferencia']}); procede {accion} sujeto a aprobación.")
        return out

    # ---- modalidades ---------------------------------------------------------------------------
    def _transcribir(self, ruta: Path) -> str:
        sidecar = ruta.with_suffix(".txt")
        return sidecar.read_text(encoding="utf-8").strip() if sidecar.exists() else ""

    def _extraer_constancia(self, ruta: Path):
        try:
            with Image.open(ruta) as im:
                meta = im.info.get("constancia_json")
        except Exception:
            meta = None
        if not meta:
            return {"es_constancia_pago": False, "confianza": 0.9}, Uso(800, 20), "mock-vision"
        datos = json.loads(meta)
        datos.update(es_constancia_pago=True, confianza=0.95)
        return datos, Uso(900, 120), "mock-vision"

    def _sintetizar(self, texto: str, destino: Path) -> Path:
        segundos = min(20.0, max(0.6, len(texto) * 0.03))
        tasa = 16000
        with wave.open(str(destino), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(tasa)
            frames = bytearray()
            for i in range(int(segundos * tasa)):
                f = 330 + 40 * ((i // 4000) % 4)
                frames += struct.pack("<h", int(2500 * math.sin(2 * math.pi * f * i / tasa)))
            w.writeframes(bytes(frames))
        return destino

    def _embeber(self, textos: list[str]) -> list[list[float]]:
        vectores = []
        for t in textos:
            v = [0.0] * 256
            for palabra in re.findall(r"\w+", t.lower()):
                v[int(hashlib.md5(palabra.encode()).hexdigest(), 16) % 256] += 1.0
            norma = math.sqrt(sum(x * x for x in v)) or 1.0
            vectores.append([x / norma for x in v])
        return vectores
