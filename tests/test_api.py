"""API HTTP: contrato OpenAPI, subida multipart, HITL protegido, problem+json y solo-audio."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import reclamos.api.app as appmod

H_ANALISTA = {"X-Analista-Key": "demo-analista"}


@pytest.fixture()
def cliente(servicio):
    appmod._servicio = servicio  # sin lifespan: se comparte el servicio de la sesión de pruebas (Qdrant local = 1 proceso)
    return TestClient(appmod.app)


def _subir(cliente, ses, rutas, esc, **extra):
    with open(rutas["audio"], "rb") as a, open(rutas["imagen"], "rb") as i:
        return cliente.post("/api/v1/reclamos", data={"sesion_id": ses["sesion_id"], "otp": ses["otp_demo"],
                                                      "texto": esc.relato, **extra},
                            files={"audio": ("relato.wav", a, "audio/wav"), "imagen": ("c.png", i, "image/png")},
                            headers={"Idempotency-Key": "api-test-1"})


def test_openapi_expone_las_rutas(cliente):
    paths = cliente.get("/openapi.json").json()["paths"]
    for p in ("/api/v1/sesiones", "/api/v1/reclamos", "/api/v1/aprobaciones",
              "/api/v1/aprobaciones/{aprobacion_id}/decision", "/api/v1/health"):
        assert p in paths


def test_flujo_http_completo_con_hitl(cliente, escenario):
    esc, _, rutas = escenario("DUPLICADA")
    ses = cliente.post("/api/v1/sesiones", json={"caso_id": "C-07", "semilla": 4213}).json()
    r = _subir(cliente, ses, rutas, esc)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["pendiente_hitl"] and cuerpo["audio_url"]
    assert cliente.get(cuerpo["audio_url"]).status_code == 200

    assert cliente.get("/api/v1/aprobaciones").status_code == 401  # sin clave de analista
    pend = cliente.get("/api/v1/aprobaciones", headers=H_ANALISTA).json()
    assert [p["aprobacion_id"] for p in pend] == [cuerpo["aprobacion_id"]]

    d = cliente.post(f"/api/v1/aprobaciones/{cuerpo['aprobacion_id']}/decision", headers=H_ANALISTA,
                     json={"decision": "APROBADA", "motivo": "validado", "aprobador": "ana", "rol": "SUPERVISOR"})
    assert d.status_code == 200, d.text
    assert d.json()["respuesta"]["accion_final"] == esc.accion_esperada
    again = cliente.post(f"/api/v1/aprobaciones/{cuerpo['aprobacion_id']}/decision", headers=H_ANALISTA,
                         json={"decision": "RECHAZADA", "motivo": "otra vez", "aprobador": "ana", "rol": "SUPERVISOR"})
    assert again.status_code == 409 and again.headers["content-type"].startswith("application/problem+json")
    est = cliente.get(f"/api/v1/reclamos/{cuerpo['ticket_id']}").json()
    assert est["accion_ejecutada"] == esc.accion_esperada


def test_formato_no_admitido_y_sesion_inexistente(cliente, escenario, tmp_path):
    esc, ses, rutas = escenario("DUPLICADA")
    malo = tmp_path / "a.exe"
    malo.write_bytes(b"MZ")
    with open(malo, "rb") as f:
        r = cliente.post("/api/v1/reclamos", data={"sesion_id": ses["sesion_id"]}, files={"audio": ("a.exe", f)})
    assert r.status_code == 415
    r = cliente.post("/api/v1/reclamos", data={"sesion_id": "SES-NOEXISTE", "texto": "hola"})
    assert r.status_code == 404 and r.json()["title"] == "SESION_INEXISTENTE"


def test_audio_no_permite_salir_del_directorio(cliente):
    assert cliente.get("/api/v1/audio/..%2F..%2F.env").status_code == 404
