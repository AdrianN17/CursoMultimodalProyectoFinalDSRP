"""Reglas determinísticas de formato de la 'Constancia de Pago' (la percepción visual NO se acepta a ciegas)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "set": 9,
         "oct": 10, "nov": 11, "dic": 12}
_RE_FECHA = re.compile(r"^(\d{1,2}) (" + "|".join(MESES) + r") (\d{4})$", re.I)
_RE_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# La constancia muestra 5 dígitos finales (ej. 23223); en BD se guardan 4: se comparan los últimos 4.
_RE_TARJETA = re.compile(r"^(?:[Xx*]{4} ){3}(\d{4,5})$")
_RE_CODIGO = re.compile(r"^\d{6,8}$")
_RE_MONTO = re.compile(r"^(S/|US\$|\$)\s*(\d{1,3}(?:,\d{3})*|\d+)\.(\d{2})$")


@dataclass
class ResultadoConstancia:
    valida: bool
    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    moneda: str | None = None
    monto: float | None = None
    codigo_operacion: str | None = None
    fecha: date | None = None
    hora: str | None = None
    ultimos4: str | None = None
    empresa: str | None = None
    servicio: str | None = None
    producto: str | None = None
    confianza: float | None = None

    def a_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["fecha"] = self.fecha.isoformat() if self.fecha else None
        return d


def validar_constancia(d: dict, confianza_minima: float = 0.4) -> ResultadoConstancia:
    r = ResultadoConstancia(valida=False, confianza=d.get("confianza"))
    if not d.get("es_constancia_pago"):
        r.errores.append("NO_ES_CONSTANCIA_DE_PAGO")
        return r

    if (d.get("titulo") or "").strip().lower() != "constancia de pago":
        r.errores.append("TITULO_INVALIDO")

    m = _RE_FECHA.match((d.get("fecha") or "").strip())
    if not m:
        r.errores.append("FECHA_FORMATO_INVALIDO")
    else:
        try:
            r.fecha = date(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            r.errores.append("FECHA_INEXISTENTE")

    if not _RE_HORA.match((d.get("hora") or "").strip()):
        r.errores.append("HORA_FORMATO_INVALIDO")
    else:
        r.hora = d["hora"].strip()

    t = _RE_TARJETA.match((d.get("tarjeta_mascara") or "").strip())
    if not t:
        r.errores.append("TARJETA_FORMATO_INVALIDO")
    else:
        r.ultimos4 = t.group(1)[-4:]

    for campo, destino in (("empresa", "empresa"), ("servicio", "servicio"), ("cuenta_producto", "producto")):
        valor = (d.get(campo) or "").strip()
        if not valor:
            r.errores.append(f"{campo.upper()}_VACIO")
        else:
            setattr(r, destino, valor)

    nombre = (d.get("nombre") or "").strip()
    if not nombre:
        r.errores.append("NOMBRE_VACIO")
    elif "*" not in nombre:
        r.advertencias.append("NOMBRE_SIN_ENMASCARAR_PII")

    codigo = str(d.get("codigo_operacion") or "").strip()
    if not _RE_CODIGO.match(codigo):
        r.errores.append("CODIGO_OPERACION_INVALIDO")
    else:
        r.codigo_operacion = codigo

    mm = _RE_MONTO.match((d.get("monto_texto") or "").strip())
    if not mm:
        r.errores.append("MONTO_FORMATO_INVALIDO")
    else:
        r.moneda = "PEN" if mm.group(1) == "S/" else "USD"
        r.monto = float(mm.group(2).replace(",", "") + "." + mm.group(3))

    if r.confianza is not None and r.confianza < confianza_minima:
        r.errores.append("CONFIANZA_DE_EXTRACCION_BAJA")

    r.valida = not r.errores
    return r
