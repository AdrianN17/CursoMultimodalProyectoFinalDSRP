"""Pruebas unitarias sin IA ni BD: semilla, validador de constancia y motor de políticas."""
from __future__ import annotations

from datetime import datetime

import pytest

from reclamos.escenario import TIPOS_CASO, construir_escenario
from reclamos.politicas.motor import ContextoPolitica, evaluar
from reclamos.validadores.constancia import validar_constancia


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
        assert forzado.cliente_id == base.cliente_id and forzado.otp == base.otp


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


# ---------------------------------------------------------------- motor
def _tx(**kw):
    base = dict(transaccion_id="T1", monto=250.0, pertenece_al_cliente=True, anulada=False, facturada=False,
                tarjeta_habilitada=True, fecha_hora=datetime(2025, 1, 10))
    return {**base, **kw}


def _ctx(**kw):
    base = dict(otp_verificado=True, evidencia_valida=True, moneda="PEN", monto_constancia=250.0,
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
    (dict(otp_verificado=False), "RECHAZAR", "P-07"),
    (dict(moneda="USD"), "NO_DISPONIBLE_MONEDA", "P-09"),
    (dict(evidencia_valida=False), "PEDIR_INFO", "P-02"),
    (dict(tx=_tx(pertenece_al_cliente=False)), "RECHAZAR", "P-04"),
    (dict(monto_constancia=999.0), "ESCALAR_OPERADOR", "P-10"),
    (dict(accion_previa_en_ticket=True), "RECHAZAR", "P-05"),
    (dict(tx=_tx(tarjeta_habilitada=False)), "ESCALAR_OPERADOR", "P-06"),
    (dict(tx=None), "ESCALAR_OPERADOR", "P-10"),
])
def test_motor_reglas_de_rechazo_escalado_e_informacion(kw, accion, politica):
    d = evaluar(_ctx(**kw))
    assert d.accion == accion and politica in d.politicas
    assert not d.requiere_hitl


def test_motor_registra_discrepancia_de_monto_con_dato_maestro_ganador():
    d = evaluar(_ctx(monto_constancia=999.0))
    assert d.discrepancias[0]["campo"] == "monto" and d.discrepancias[0]["maestro"] == "250.00"


def test_manipulacion_solo_agrega_alerta_no_cambia_la_decision():
    assert evaluar(_ctx(intento_manipulacion=True)).accion == evaluar(_ctx()).accion
    assert "INTENTO_DE_MANIPULACION_DETECTADO" in evaluar(_ctx(intento_manipulacion=True)).alertas
