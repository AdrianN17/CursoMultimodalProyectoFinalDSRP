"""Pruebas unitarias sin IA ni BD: semilla, validador de constancia y motor de políticas."""
from __future__ import annotations

from datetime import datetime

import pytest

from reclamos.db import calificar
from reclamos.escenario import TIPOS_CASO, construir_escenario
from reclamos.politicas.motor import ContextoPolitica, evaluar
from reclamos.validadores.constancia import validar_constancia


# ---------------------------------------------------------------- esquema SQL
@pytest.mark.parametrize("sql,esperado", [
    ("SELECT * FROM Ticket WHERE ticket_id = ?", "SELECT * FROM [multimodal].[Ticket] WHERE ticket_id = ?"),
    ("UPDATE Transaccion SET anulada = 1", "UPDATE [multimodal].[Transaccion] SET anulada = 1"),
    ("INSERT INTO TicketEvento (ticket_id) VALUES (?)", "INSERT INTO [multimodal].[TicketEvento] (ticket_id) VALUES (?)"),
    ("FROM Transaccion t1 JOIN Transaccion t2 ON t2.g = t1.g",
     "FROM [multimodal].[Transaccion] t1 JOIN [multimodal].[Transaccion] t2 ON t2.g = t1.g"),
    ("IF OBJECT_ID('checkpoints') IS NULL CREATE TABLE checkpoints (a INT)",
     "IF OBJECT_ID('multimodal.checkpoints') IS NULL CREATE TABLE [multimodal].[checkpoints] (a INT)"),
    ("DELETE FROM checkpoint_writes WHERE thread_id = ?", "DELETE FROM [multimodal].[checkpoint_writes] WHERE thread_id = ?"),
])
def test_calificar_antepone_el_esquema_a_las_tablas_del_proyecto(sql, esperado):
    assert calificar(sql, "multimodal") == esperado


@pytest.mark.parametrize("sql", [
    "SELECT * FROM [otro].[Ticket]",            # ya calificada
    "SELECT * FROM multimodal.Ticket",          # ya calificada
    "SELECT name FROM sys.tables",              # objeto de sistema
    "SELECT * FROM TablaAjena",                 # no es del proyecto
])
def test_calificar_no_toca_lo_que_no_corresponde(sql):
    assert calificar(sql, "multimodal") == sql


def test_calificar_con_esquema_vacio_no_cambia_nada():
    sql = "SELECT * FROM Ticket"
    assert calificar(sql, "") == sql



# ---------------------------------------------------------------- semilla
def test_semilla_es_determinista():
    a, b = construir_escenario("C-07", 4213), construir_escenario("C-07", 4213)
    assert a == b


def test_semillas_distintas_cambian_el_escenario():
    a, b = construir_escenario("C-07", 4213), construir_escenario("C-07", 9999)
    assert (a.cliente_id, a.monto_bd, a.tx_principal_codigo) != (b.cliente_id, b.monto_bd, b.tx_principal_codigo)


def test_forzar_tipo_no_desplaza_el_resto_de_elementos():
    base = construir_escenario("C-07", 4213)
    for tipo in TIPOS_CASO:
        forzado = construir_escenario("C-07", 4213, tipo)
        assert forzado.tipo == tipo
        assert forzado.cliente_id == base.cliente_id and forzado.umbral_hitl == base.umbral_hitl


def _extraido(c: dict) -> dict:
    """Lo que devolvería el visor: los campos + el veredicto 'es constancia' y la confianza."""
    return {**c, "es_constancia_pago": True, "confianza": 0.95}


@pytest.mark.parametrize("tipo", TIPOS_CASO)
def test_la_constancia_del_escenario_es_valida_salvo_sin_evidencia(tipo):
    esc = construir_escenario("C-07", 4213, tipo)
    if tipo == "SIN_EVIDENCIA":
        assert esc.constancia is None
    else:
        r = validar_constancia(_extraido(esc.constancia))
        assert r.valida, r.errores
        assert r.moneda == ("USD" if tipo == "MONEDA_USD" else "PEN")


# ---------------------------------------------------------------- validador
def _base():
    return _extraido(construir_escenario("C-07", 4213, "DUPLICADA").constancia)


@pytest.mark.parametrize("campo", ["codigo_operacion", "monto_texto", "tarjeta_mascara", "empresa", "fecha"])
def test_constancia_incompleta_es_invalida(campo):
    c = _base()
    c[campo] = ""
    assert not validar_constancia(c).valida


def test_constancia_acepta_tarjeta_de_4_o_5_digitos_finales():
    c = _base()
    ult4 = c["tarjeta_mascara"][-4:]
    c["tarjeta_mascara"] = f"**** **** **** {ult4}"
    assert validar_constancia(c).ultimos4 == ult4
    c["tarjeta_mascara"] = f"XXXX XXXX XXXX 5{ult4}"
    r = validar_constancia(c)
    assert r.valida and r.ultimos4 == ult4


@pytest.mark.parametrize("confianza,valida", [(0.9, True), ("0.8", True), ("<número entre 0 y 1>", True),
                                              (None, True), (0.0, False)])
def test_confianza_no_numerica_no_rompe_el_validador(confianza, valida):
    c = _base()
    c["confianza"] = confianza
    r = validar_constancia(c)
    assert r.valida is valida
    assert (r.confianza is None) == (confianza in (None, "<número entre 0 y 1>"))


# ---------------------------------------------------------------- motor
def _tx(**kw):
    base = dict(transaccion_id="T1", monto=250.0, pertenece_al_cliente=True, anulada=False, facturada=False,
                tarjeta_habilitada=True, fecha_hora=datetime(2025, 1, 10))
    return {**base, **kw}


def _ctx(**kw):
    base = dict(evidencia_valida=True, moneda="PEN", monto_constancia=250.0,
                intencion="DUPLICADO", tx=_tx(), duplicados=[_tx(transaccion_id="T0", fecha_hora=datetime(2025, 1, 9)),
                                                              _tx()])
    return ContextoPolitica(**{**base, **kw})


def test_motor_anula_la_repetida_antes_de_facturar():
    d = evaluar(_ctx())
    assert d.accion == "ANULACION" and d.transaccion_objetivo_id == "T1" and d.requiere_hitl
    assert d.rol_requerido == "ANALISTA"


def test_motor_reembolsa_si_ya_facturo_y_exige_supervisor_sobre_umbral():
    c = _ctx(tx=_tx(facturada=True, monto=1500.0), monto_constancia=1500.0,
             duplicados=[_tx(transaccion_id="T0", monto=1500.0, fecha_hora=datetime(2025, 1, 9)),
                         _tx(monto=1500.0, facturada=True)])
    d = evaluar(c)
    assert d.accion == "REEMBOLSO" and d.rol_requerido == "SUPERVISOR"


@pytest.mark.parametrize("kw,accion,politica", [
    (dict(moneda="USD"), "NO_DISPONIBLE_MONEDA", "P-09"),
    (dict(evidencia_valida=False), "PEDIR_INFO", "P-02"),
    (dict(tx=_tx(pertenece_al_cliente=False)), "RECHAZAR", "P-04"),
    (dict(monto_constancia=999.0), "ESCALAR_OPERADOR", "P-10"),
    (dict(accion_previa_en_ticket=True), "RECHAZAR", "P-05"),
    (dict(tx=_tx(tarjeta_habilitada=False)), "ESCALAR_OPERADOR", "P-06"),
    (dict(tx=None), "ESCALAR_OPERADOR", "P-10"),
    (dict(intencion="SIN_CONSENTIMIENTO", tx=_tx(autenticada_otp=True)), "ESCALAR_OPERADOR", "P-11"),
])
def test_motor_reglas_de_rechazo_escalado_e_informacion(kw, accion, politica):
    d = evaluar(_ctx(**kw))
    assert d.accion == accion and politica in d.politicas
    assert not d.requiere_hitl


def test_sin_consentimiento_y_sin_otp_en_la_operacion_sigue_el_flujo_de_reclamo():
    d = evaluar(_ctx(intencion="SIN_CONSENTIMIENTO", tx=_tx(autenticada_otp=False)))
    assert d.accion == "ANULACION" and d.requiere_hitl


def test_motor_registra_discrepancia_de_monto_con_dato_maestro_ganador():
    d = evaluar(_ctx(monto_constancia=999.0))
    assert d.discrepancias[0]["campo"] == "monto" and d.discrepancias[0]["maestro"] == "250.00"


def test_manipulacion_solo_agrega_alerta_no_cambia_la_decision():
    assert evaluar(_ctx(intento_manipulacion=True)).accion == evaluar(_ctx()).accion
    assert "INTENTO_DE_MANIPULACION_DETECTADO" in evaluar(_ctx(intento_manipulacion=True)).alertas

# ---------------------------------------------------------------- voz (Azure Speech, sin red)
def _proveedor_azure():
    from dataclasses import replace

    from reclamos.config import get_settings
    from reclamos.proveedores.azure_openai import ProveedorAzure
    s = replace(get_settings(), azure_endpoint="https://x.openai.azure.com", azure_api_key="k",
                speech_endpoint="https://x.cognitiveservices.azure.com", speech_key="clave-voz")
    return ProveedorAzure(s)


class _Resp:
    def __init__(self, contenido=b"", json_=None):
        self.status_code, self.content, self._json = 200, contenido, json_

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


def test_stt_usa_mai_transcribe_y_une_las_frases(monkeypatch, tmp_path):
    llamadas = {}

    def falso(metodo, url, **kw):
        llamadas.update(url=url, kw=kw)
        return _Resp(json_={"combinedPhrases": [{"text": "Hola, me cobraron dos veces."}]})

    monkeypatch.setattr("httpx.request", falso)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF....")
    assert _proveedor_azure()._transcribir(wav) == "Hola, me cobraron dos veces."
    assert llamadas["url"].endswith("/speechtotext/transcriptions:transcribe?api-version=2025-10-15")
    assert llamadas["kw"]["headers"]["Ocp-Apim-Subscription-Key"] == "clave-voz"
    assert "mai-transcribe-1.5" in llamadas["kw"]["data"]["definition"]


def test_tts_usa_mai_voice_y_escapa_el_ssml(monkeypatch, tmp_path):
    llamadas = {}

    def falso(metodo, url, **kw):
        llamadas.update(url=url, kw=kw)
        return _Resp(contenido=b"ID3audio")

    monkeypatch.setattr("httpx.request", falso)
    destino = tmp_path / "r.mp3"
    _proveedor_azure()._sintetizar("Reembolso <S/ 100> & más", destino)
    ssml = llamadas["kw"]["content"].decode()
    assert "es-ES-Marta:MAI-Voice-2" in ssml and "&lt;S/ 100&gt; &amp; más" in ssml
    assert llamadas["url"].endswith("/tts/cognitiveservices/v1")
    assert destino.read_bytes() == b"ID3audio"

# ---------------------------------------------------------------- registro paso a paso (temporal/)
def test_cada_ejecucion_escribe_un_log_con_fecha_en_temporal(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    codigo = (
        "import logging\n"
        "from reclamos.observabilidad.otel import iniciar_registro, trazar\n"
        "iniciar_registro('prueba')\n"
        "logging.getLogger('reclamos.prueba').info('hola paso a paso')\n"
        "with trazar('nodo.demo'):\n"
        "    logging.getLogger('reclamos.prueba').debug('detalle interno')\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "REGISTRO_ARCHIVO"}
    env.update(PYTHONPATH=str(raiz / "src"), TEMPORAL_DIR=str(tmp_path / "temporal"),
               EVIDENCIA_DIR=str(tmp_path / "evidencia"), PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, "-c", codigo], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-500:]
    ficheros = list((tmp_path / "temporal").glob("prueba_????-??-??_??-??-??.log"))
    assert len(ficheros) == 1, "debe crearse un fichero por ejecución con la fecha y hora en el nombre"
    texto = ficheros[0].read_text(encoding="utf-8")
    for esperado in ("hola paso a paso", "detalle interno", "-> nodo.demo", "<- nodo.demo", "registro iniciado"):
        assert esperado in texto, esperado
    assert "detalle interno" not in p.stderr, "el nivel DEBUG va solo al fichero, no a la consola"
