"""Escenario sintético determinístico. AQUÍ ACTÚA LA SEMILLA.

`construir_escenario(caso_id, semilla)` deriva TODO lo aleatorio de un único `random.Random`.
Elementos del escenario que la semilla modifica (cada uno cambia la decisión del agente):

  1. Datos maestros de BD: montos, códigos de operación, saldos, nombres enmascarados.
  2. Ciclo de facturación (día de corte) y fecha de la operación -> decide ANULACIÓN vs REEMBOLSO (P-03).
  3. Tipo de caso (duplicada, sin consentimiento, monto discrepante, tarjeta deshabilitada, ...).
  4. Estado de la tarjeta (habilitada/deshabilitada) -> decide si pasa a operador (P-06).
  5. Umbral de monto para aprobación reforzada (rol SUPERVISOR) en el HITL.
  6. Datos de la constancia de pago (fecha, hora, monto, código) usados para generar la imagen.
  7. OTP simulado del cliente.
  8. Si la operación reclamada se autenticó con OTP o no (indicio de fraude, política P-11).

`tipo` puede forzarse (pruebas/demo) pero todos los demás valores siguen dependiendo de la semilla.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..politicas.calendario import esta_facturada, ultimo_corte

TIPOS_CASO = [
    "DUPLICADA",
    "SIN_CONSENTIMIENTO",
    "MONTO_DISCREPANTE",
    "TARJETA_DESHABILITADA",
    "SIN_EVIDENCIA",
    "AJENA",
    "MONEDA_USD",
    "SIN_CONSENTIMIENTO_CON_OTP",
]
PESOS_TIPO = [3, 3, 2, 1, 1, 1, 1, 0]  # peso 0: solo se obtiene forzando --tipo (mantiene reproducibles las semillas previas)
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

NOMBRES = ["Adriana", "Bruno", "Carla", "Diego", "Elena", "Fabio", "Gloria", "Hugo", "Irene", "Jorge"]
APELLIDOS = ["Traverso", "Unidad", "Quispe", "Salazar", "Mendoza", "Paredes", "Rojas", "Villar", "Campos", "Torres"]


@dataclass(frozen=True)
class ServicioSeed:
    servicio_id: int
    empresa: str
    servicio: str
    categoria: str


CATALOGO_SERVICIOS = [
    ServicioSeed(1, "Pluz Energia", "SERVICIO DE ELECTRICIDAD", "LUZ"),
    ServicioSeed(2, "Aguas del Sur", "SERVICIO DE AGUA POTABLE", "AGUA"),
    ServicioSeed(3, "TeleNova", "SERVICIO DE INTERNET Y TELEFONIA", "TELECOM"),
    ServicioSeed(4, "GasAndes", "SERVICIO DE GAS NATURAL", "GAS"),
    ServicioSeed(5, "Supermercados Delta", "COMPRA CON TARJETA", "RETAIL"),
    ServicioSeed(6, "Nube Market", "COMPRA ONLINE", "ONLINE"),
]


@dataclass
class ClienteSeed:
    cliente_id: str
    nombre_mask: str
    doc_hash: str
    email_mask: str
    segmento: str


@dataclass
class CuentaSeed:
    cuenta_id: str
    cliente_id: str
    tipo: str
    saldo: float
    saldo_disponible: float


@dataclass
class TarjetaSeed:
    tarjeta_id: str
    cuenta_id: str
    ultimos4: str
    producto: str
    habilitada: bool
    dia_facturacion: int


@dataclass
class TransaccionSeed:
    transaccion_id: str
    codigo_operacion: str
    tarjeta_id: str
    servicio_id: int
    monto: float
    fecha_hora: datetime
    canal: str
    grupo_duplicado: str | None = None
    autenticada_otp: bool = True


@dataclass
class Escenario:
    caso_id: str
    semilla: int
    tipo: str
    fecha_referencia: date
    umbral_hitl: int
    otp: str
    cliente_id: str
    otro_cliente_id: str
    clientes: list[ClienteSeed] = field(default_factory=list)
    cuentas: list[CuentaSeed] = field(default_factory=list)
    tarjetas: list[TarjetaSeed] = field(default_factory=list)
    transacciones: list[TransaccionSeed] = field(default_factory=list)
    tx_principal_codigo: str = ""
    tx_objetivo_codigo: str = ""
    facturada: bool = False
    constancia: dict | None = None
    relato: str = ""
    monto_bd: float = 0.0

    @property
    def accion_esperada(self) -> str:
        """Resultado esperado del motor para este escenario (se usa en pruebas y evidencia)."""
        if self.tipo in ("DUPLICADA", "SIN_CONSENTIMIENTO"):
            return "REEMBOLSO" if self.facturada else "ANULACION"
        return {
            "TARJETA_DESHABILITADA": "ESCALAR_OPERADOR",
            "MONTO_DISCREPANTE": "ESCALAR_OPERADOR",
            "SIN_EVIDENCIA": "PEDIR_INFO",
            "AJENA": "RECHAZAR",
            "MONEDA_USD": "NO_DISPONIBLE_MONEDA",
            "SIN_CONSENTIMIENTO_CON_OTP": "ESCALAR_OPERADOR",
        }[self.tipo]


def _mask_nombre(nombre: str, ap1: str, ap2: str) -> str:
    return f"{nombre[0]}** {ap1[:3]}** {ap2[:4]}**"


def _fmt_monto(m: float) -> str:
    return f"S/ {m:,.2f}"


def _fecha_constancia(dt: datetime) -> str:
    return f"{dt.day:02d} {MESES[dt.month - 1]} {dt.year}"


def construir_escenario(caso_id: str, semilla: int, tipo: str | None = None) -> Escenario:
    rng = random.Random(f"{caso_id}:{semilla}")

    # --- elemento 3: tipo de caso -----------------------------------------------------------
    tipo_sorteado = rng.choices(TIPOS_CASO, weights=PESOS_TIPO)[0]  # siempre se consume para mantener el flujo
    tipo_final = tipo or tipo_sorteado
    if tipo_final not in TIPOS_CASO:
        raise ValueError(f"tipo de caso desconocido: {tipo_final}")

    # --- elemento 5 y 7: umbral HITL reforzado y OTP simulado ------------------------------
    umbral_hitl = rng.choice([500, 1000, 2000])
    otp = f"{rng.randint(0, 999999):06d}"

    # --- elemento 2: fecha de referencia, ciclo de facturación y fecha de la operación ------
    fecha_ref = date(2026, 10, 9) + timedelta(days=rng.randint(0, 12))
    quiere_facturada = rng.random() < 0.5
    dias_corte = [d for d in (5, 12, 20, 28) if d != fecha_ref.day]
    dia_fact = rng.choice(dias_corte)
    corte = ultimo_corte(fecha_ref, dia_fact)
    if quiere_facturada:
        fecha_op = corte - timedelta(days=rng.randint(1, 20))
    else:
        fecha_op = corte + timedelta(days=rng.randint(1, (fecha_ref - corte).days))
    hora_op = datetime.combine(fecha_op, datetime.min.time()) + timedelta(
        hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
    )
    facturada = esta_facturada(fecha_op, fecha_ref, dia_fact)

    # --- elemento 1: datos maestros -----------------------------------------------------------
    monto = round(rng.uniform(40, 2600), 2)
    servicio = rng.choice(CATALOGO_SERVICIOS)
    if tipo_final in ("SIN_CONSENTIMIENTO", "SIN_CONSENTIMIENTO_CON_OTP"):
        servicio = CATALOGO_SERVICIOS[5]
    codigos: set[str] = set()

    def nuevo_codigo() -> str:
        while True:
            c = f"{rng.randint(1000, 9999999):07d}"
            if c not in codigos:
                codigos.add(c)
                return c

    ids = rng.sample(range(1000, 9999), 2)
    cliente_id, otro_id = f"CLI-{ids[0]}", f"CLI-{ids[1]}"

    def crear_cliente(cid: str) -> ClienteSeed:
        n, a1, a2 = rng.choice(NOMBRES), rng.choice(APELLIDOS), rng.choice(APELLIDOS)
        doc = hashlib.sha256(f"DNI-SINTETICO-{rng.randint(10_000_000, 99_999_999)}".encode()).hexdigest()
        return ClienteSeed(cid, _mask_nombre(n, a1, a2), doc, f"{n[0].lower()}***@ejemplo.test",
                           rng.choice(["PERSONAL", "PREMIUM"]))

    esc = Escenario(
        caso_id=caso_id, semilla=semilla, tipo=tipo_final, fecha_referencia=fecha_ref,
        umbral_hitl=umbral_hitl, otp=otp, cliente_id=cliente_id, otro_cliente_id=otro_id,
        facturada=facturada, monto_bd=monto,
    )
    esc.clientes = [crear_cliente(cliente_id), crear_cliente(otro_id)]

    # --- elemento 4: estado de la tarjeta -----------------------------------------------------
    tarjetas_por_cliente: dict[str, TarjetaSeed] = {}
    for cid, producto in ((cliente_id, "Visa Infinite Soles"), (otro_id, "Mastercard Platinum Soles")):
        n = cid.split("-")[1]
        saldo = round(rng.uniform(500, 9000), 2)
        esc.cuentas.append(CuentaSeed(f"CTA-{n}-A", cid, "AHORROS", saldo, saldo))
        saldo_t = round(rng.uniform(300, 4000), 2)
        esc.cuentas.append(CuentaSeed(f"CTA-{n}-T", cid, "TARJETA", saldo_t, round(saldo_t * 0.8, 2)))
        habilitada = not (cid == cliente_id and tipo_final == "TARJETA_DESHABILITADA")
        t = TarjetaSeed(f"TRJ-{n}", f"CTA-{n}-T", f"{rng.randint(0, 9999):04d}", producto, habilitada,
                        dia_fact)
        esc.tarjetas.append(t)
        tarjetas_por_cliente[cid] = t

    tarj = tarjetas_por_cliente[cliente_id]
    tarj_otro = tarjetas_por_cliente[otro_id]
    duenio_tx = tarj_otro if tipo_final == "AJENA" else tarj

    codigo = nuevo_codigo()
    canal = "ONLINE" if tipo_final in ("SIN_CONSENTIMIENTO", "SIN_CONSENTIMIENTO_CON_OTP") \
        else rng.choice(["POS", "ONLINE", "APP"])
    grupo = f"DUP-{rng.randint(100, 999)}" if tipo_final == "DUPLICADA" else None
    principal = TransaccionSeed(f"TX-{codigo}", codigo, duenio_tx.tarjeta_id, servicio.servicio_id, monto,
                                hora_op, canal, grupo)
    # --- elemento 8: autenticación OTP de la operación (indicio de fraude, P-11) -------------
    # Quien desconoce una compra "sin OTP" tiene un reclamo fuerte; con OTP validado se escala a un operador.
    principal.autenticada_otp = tipo_final not in ("SIN_CONSENTIMIENTO", "TARJETA_DESHABILITADA")
    esc.transacciones.append(principal)
    esc.tx_principal_codigo = esc.tx_objetivo_codigo = codigo

    if tipo_final == "DUPLICADA":
        c2 = nuevo_codigo()
        esc.transacciones.append(TransaccionSeed(
            f"TX-{c2}", c2, tarj.tarjeta_id, servicio.servicio_id, monto,
            hora_op + timedelta(minutes=rng.randint(1, 4)), canal, grupo))
        esc.tx_objetivo_codigo = c2  # la anulable es la repetida (la segunda)

    n_previas = len(esc.transacciones)
    for tarjeta_dec, n_dec in ((tarj, rng.randint(3, 5)), (tarj_otro, 2)):
        for _ in range(n_dec):
            s = rng.choice(CATALOGO_SERVICIOS)
            c = nuevo_codigo()
            dt = datetime.combine(fecha_ref - timedelta(days=rng.randint(2, 60)), datetime.min.time()) + \
                timedelta(hours=rng.randint(8, 22), minutes=rng.randint(0, 59))
            esc.transacciones.append(TransaccionSeed(
                f"TX-{c}", c, tarjeta_dec.tarjeta_id, s.servicio_id, round(rng.uniform(15, 600), 2), dt,
                rng.choice(["POS", "ONLINE", "APP"])))

    # RNG aparte: así el resto del escenario no cambia respecto a semillas anteriores.
    rng_otp = random.Random(f"{caso_id}:{semilla}:otp")
    for tx in esc.transacciones[n_previas:]:
        tx.autenticada_otp = rng_otp.random() > 0.25  # ~25 % de operaciones de relleno sin OTP
    # --- elemento 6: contenido de la constancia (imagen) --------------------------------------
    cliente_dueno = esc.clientes[1] if tipo_final == "AJENA" else esc.clientes[0]
    sufijo5 = f"{rng.randint(1, 9)}{duenio_tx.ultimos4}"
    monto_img = monto
    if tipo_final == "MONTO_DISCREPANTE":
        monto_img = max(10.0, round(monto * rng.uniform(0.05, 0.6), 2))
    constancia = {
        "titulo": "Constancia de Pago",
        "fecha": _fecha_constancia(hora_op),
        "hora": hora_op.strftime("%H:%M"),
        "cuenta_producto": duenio_tx.producto,
        "tarjeta_mascara": f"XXXX XXXX XXXX {sufijo5}",
        "empresa": servicio.empresa,
        "servicio": servicio.servicio,
        "nombre": cliente_dueno.nombre_mask,
        "codigo_operacion": codigo,
        "monto_texto": _fmt_monto(monto_img),
    }
    if tipo_final == "MONEDA_USD":
        constancia["monto_texto"] = f"US$ {round(monto_img / 3.7, 2):,.2f}"
        constancia["codigo_operacion"] = nuevo_codigo()
    esc.constancia = None if tipo_final == "SIN_EVIDENCIA" else constancia

    esc.relato = _relato(tipo_final, servicio.empresa, monto, constancia["monto_texto"])
    return esc


def _relato(tipo: str, empresa: str, monto: float, monto_img_txt: str) -> str:
    m = _fmt_monto(monto)
    plantillas = {
        "DUPLICADA": f"Hola, me cobraron dos veces la misma compra en {empresa} por {m}. "
                     f"Adjunto mi constancia de pago. Quiero que me devuelvan el dinero.",
        "SIN_CONSENTIMIENTO": f"Hola, no reconozco el cobro de {m} en {empresa}. Yo no autoricé "
                              f"esa operación. Adjunto la constancia que me llegó.",
        "SIN_CONSENTIMIENTO_CON_OTP": f"Hola, no reconozco el cobro de {m} en {empresa}. Yo no autoricé "
                                      f"esa operación. Adjunto la constancia que me llegó.",
        "MONTO_DISCREPANTE": f"Hola, hice una compra en {empresa} pero el importe cobrado es incorrecto, "
                             f"me cobraron {m}. Adjunto mi constancia de pago.",
        "TARJETA_DESHABILITADA": f"Hola, no reconozco el cobro de {m} en {empresa}, no lo autoricé. "
                                 f"Adjunto la constancia de pago.",
        "SIN_EVIDENCIA": f"Hola, veo un cobro de {m} en {empresa} que no reconozco, pero no tengo la boleta.",
        "AJENA": f"Hola, quiero anular el cobro de {m} en {empresa}. Adjunto la constancia de pago.",
        "MONEDA_USD": f"Hola, quiero reclamar un cobro en dólares de {monto_img_txt} en {empresa}. "
                      f"Adjunto la constancia de pago.",
    }
    return plantillas[tipo]
