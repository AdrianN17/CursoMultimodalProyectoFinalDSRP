"""Tools de negocio (consulta + acción) sobre Azure SQL. Las expone el servidor MCP y también el modo in-process.

Todas devuelven un sobre {"ok": bool, "data": {...}} | {"ok": False, "error": {"codigo", "mensaje"}}:
el agente nunca recibe excepciones ni escribe SQL; cada tool valida y limita lo que puede hacer.
"""
from __future__ import annotations

import functools
import hashlib
import json
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Callable

import pyodbc

from .. import db
from ..config import get_settings
from ..politicas.calendario import esta_facturada, sumar_dias_habiles
from .dto import TransaccionAjenaDTO, TransaccionDTO

REGISTRO: dict[str, Callable[..., dict]] = {}
ESTADOS_TICKET = {"ABIERTO", "EN_ANALISIS", "PENDIENTE_APROBACION", "EN_ESCALAMIENTO", "PENDIENTE_TECNICO", "CERRADO"}
RESOLUCIONES = {"REEMBOLSO", "ANULACION", "RECHAZADO", "INFORMATIVO", "ESCALADO", "EXPIRADO"}
SLA_REEMBOLSO_DIAS_HABILES = 7


class ToolError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


def herramienta(fn: Callable[..., dict]) -> Callable[..., dict]:
    @functools.wraps(fn)
    def envoltura(*args: Any, **kwargs: Any) -> dict:
        try:
            return {"ok": True, "data": fn(*args, **kwargs)}
        except ToolError as e:
            return {"ok": False, "error": {"codigo": e.codigo, "mensaje": e.mensaje}}
        except pyodbc.Error as e:
            return {"ok": False, "error": {"codigo": "DB_ERROR", "mensaje": f"{type(e).__name__}: {str(e)[:160]}",
                                           "reintentable": True}}
        except Exception as e:  # nunca se filtra una traza al agente
            return {"ok": False, "error": {"codigo": "ERROR_INTERNO", "mensaje": type(e).__name__}}

    REGISTRO[fn.__name__] = envoltura
    return envoltura


# ---------------------------------------------------------------------------------------------
def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _f(v: Any) -> Any:
    if hasattr(v, "quantize"):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    return v


def _fila(f: dict | None) -> dict | None:
    return {k: _f(v) for k, v in f.items()} if f else None


def _parametro(cn: pyodbc.Connection, clave: str, defecto: str) -> str:
    f = db.uno("SELECT valor FROM ParametroEscenario WHERE clave = ?", (clave,), cn)
    return f["valor"] if f else defecto


def _fecha_ref(cn: pyodbc.Connection) -> date:
    return date.fromisoformat(_parametro(cn, "fecha_referencia", date.today().isoformat()))


def _evento(cn: pyodbc.Connection, ticket_id: str, tipo: str, detalle: Any, actor: str, trace_id: str) -> None:
    db.ejecutar(
        "INSERT INTO TicketEvento (ticket_id, tipo, detalle_json, actor, trace_id) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, tipo, json.dumps(detalle, ensure_ascii=False, default=str), actor, trace_id or None), cn,
    )


def _ticket(cn: pyodbc.Connection, ticket_id: str) -> dict:
    t = db.uno("SELECT * FROM Ticket WHERE ticket_id = ?", (ticket_id,), cn)
    if not t:
        raise ToolError("TICKET_INEXISTENTE", f"No existe el ticket {ticket_id}")
    return t


# ============================== TOOLS DE CONSULTA (dato maestro) ==============================
@herramienta
def consultar_parametros() -> dict[str, Any]:
    """Parámetros del escenario cargados desde la semilla (fecha de referencia, umbral HITL...)."""
    with db.conexion() as cn:
        filas = db.consultar("SELECT clave, valor FROM ParametroEscenario", (), cn)
    return {f["clave"]: f["valor"] for f in filas}


@herramienta
def consultar_cliente(cliente_id: str, trace_id: str = "") -> dict[str, Any]:
    """Datos básicos ENMASCARADOS del cliente y sus tarjetas (solo tras verificar OTP)."""
    with db.conexion() as cn:
        c = db.uno("SELECT cliente_id, nombre_mask, email_mask, segmento, estado FROM Cliente WHERE cliente_id = ?",
                   (cliente_id,), cn)
        if not c:
            raise ToolError("CLIENTE_INEXISTENTE", f"No existe el cliente {cliente_id}")
        tarjetas = db.consultar(
            "SELECT t.ultimos4, t.producto, t.habilitada FROM Tarjeta t JOIN Cuenta cu ON cu.cuenta_id = t.cuenta_id "
            "WHERE cu.cliente_id = ?", (cliente_id,), cn)
    return {**_fila(c), "tarjetas": [{**_fila(t), "habilitada": bool(t["habilitada"])} for t in tarjetas]}


@herramienta
def consultar_transaccion(cliente_id: str, codigo_operacion: str, trace_id: str = "") -> dict[str, Any]:
    """Dato maestro de una operación por código. Si es de otro cliente NO devuelve detalle."""
    with db.conexion() as cn:
        f = db.uno(
            "SELECT t.transaccion_id, t.codigo_operacion, t.monto, t.moneda, t.fecha_hora, t.estado, t.anulada, "
            "t.canal, t.grupo_duplicado, t.autenticada_otp, s.empresa, s.servicio, tr.ultimos4, tr.producto, tr.habilitada, "
            "tr.dia_facturacion, cu.cliente_id AS duenio "
            "FROM Transaccion t JOIN Tarjeta tr ON tr.tarjeta_id = t.tarjeta_id "
            "JOIN Cuenta cu ON cu.cuenta_id = tr.cuenta_id JOIN Servicio s ON s.servicio_id = t.servicio_id "
            "WHERE t.codigo_operacion = ?", (codigo_operacion,), cn)
        if not f:
            raise ToolError("NO_ENCONTRADA", f"No existe la operación {codigo_operacion}")
        if f["duenio"] != cliente_id:
            return TransaccionAjenaDTO(codigo_operacion=codigo_operacion).model_dump()
        ref = _fecha_ref(cn)
    return TransaccionDTO(
        transaccion_id=f["transaccion_id"], codigo_operacion=f["codigo_operacion"], monto=float(f["monto"]),
        moneda=f["moneda"], fecha_hora=_f(f["fecha_hora"]), estado=f["estado"], anulada=bool(f["anulada"]),
        canal=f["canal"], grupo_duplicado=f["grupo_duplicado"],
        autenticada_otp=bool(f["autenticada_otp"]), empresa=f["empresa"], servicio=f["servicio"],
        tarjeta_ultimos4=f["ultimos4"], tarjeta_producto=f["producto"], tarjeta_habilitada=bool(f["habilitada"]),
        dia_facturacion=int(f["dia_facturacion"]),
        facturada=esta_facturada(f["fecha_hora"].date(), ref, int(f["dia_facturacion"])),
        fecha_referencia=ref.isoformat(),
    ).model_dump()


@herramienta
def buscar_duplicados(cliente_id: str, transaccion_id: str, trace_id: str = "") -> dict[str, Any]:
    """Operaciones del mismo grupo de duplicidad (solo del cliente)."""
    with db.conexion() as cn:
        filas = db.consultar(
            "SELECT t2.transaccion_id, t2.codigo_operacion, t2.monto, t2.fecha_hora, t2.anulada "
            "FROM Transaccion t1 JOIN Transaccion t2 ON t2.grupo_duplicado = t1.grupo_duplicado "
            "JOIN Tarjeta tr ON tr.tarjeta_id = t2.tarjeta_id JOIN Cuenta cu ON cu.cuenta_id = tr.cuenta_id "
            "WHERE t1.transaccion_id = ? AND t1.grupo_duplicado IS NOT NULL AND cu.cliente_id = ? "
            "ORDER BY t2.fecha_hora", (transaccion_id, cliente_id), cn)
    return {"items": [{**_fila(x), "anulada": bool(x["anulada"])} for x in filas]}


@herramienta
def consultar_ticket(ticket_id: str, trace_id: str = "") -> dict[str, Any]:
    """Estado e historial reciente de un ticket (fuente de verdad del seguimiento)."""
    with db.conexion() as cn:
        t = _ticket(cn, ticket_id)
        ev = db.consultar("SELECT TOP 8 tipo, actor, ts FROM TicketEvento WHERE ticket_id = ? ORDER BY evento_id DESC",
                          (ticket_id,), cn)
        ap = db.uno("SELECT aprobacion_id, accion_propuesta, estado, rol_requerido FROM AprobacionHitl "
                    "WHERE ticket_id = ?", (ticket_id,), cn)
        rb = db.uno("SELECT tipo, monto, medio, estado, fecha_estimada FROM Reembolso WHERE ticket_id = ?",
                    (ticket_id,), cn)
    return {"ticket": _fila(t), "eventos": [_fila(e) for e in ev], "aprobacion": _fila(ap), "reembolso": _fila(rb)}


# ============================== TOOLS DE ACCIÓN (efecto persistente) ==============================
@herramienta
def crear_ticket(cliente_id: str, tipo_reclamo: str, idem_key: str, caso_id: str, semilla: int,
                 thread_id: str = "", trace_id: str = "") -> dict[str, Any]:
    """Crea el ticket de atención de forma IDEMPOTENTE: la misma idem_key devuelve el mismo ticket."""
    ticket_id = "TKT-" + hashlib.sha256(idem_key.encode()).hexdigest()[:10].upper()
    req_hash = hashlib.sha256(f"{cliente_id}|{tipo_reclamo}|{idem_key}".encode()).hexdigest()
    for _ in range(2):
        try:
            with db.conexion() as cn:
                previo = db.uno("SELECT request_hash, ticket_id FROM IdempotencyKey WHERE idem_key = ?",
                                (idem_key,), cn)
                if previo:
                    if previo["request_hash"] != req_hash:
                        raise ToolError("IDEMPOTENCY_CONFLICT", "La idem_key ya se usó con otra solicitud")
                    t = _ticket(cn, previo["ticket_id"])
                    return {"ticket_id": t["ticket_id"], "creado": False, "estado": t["estado"]}
                db.ejecutar(
                    "INSERT INTO Ticket (ticket_id, cliente_id, tipo_reclamo, caso_id, semilla, trace_id, thread_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ticket_id, cliente_id, tipo_reclamo, caso_id, semilla, trace_id or None, thread_id or None), cn)
                db.ejecutar("INSERT INTO IdempotencyKey (idem_key, scope, request_hash, ticket_id) "
                            "VALUES (?, 'ticket', ?, ?)", (idem_key, req_hash, ticket_id), cn)
                _evento(cn, ticket_id, "TICKET_CREADO", {"tipo_reclamo": tipo_reclamo, "caso_id": caso_id,
                                                         "semilla": semilla}, "sistema", trace_id)
            return {"ticket_id": ticket_id, "creado": True, "estado": "ABIERTO"}
        except pyodbc.IntegrityError:
            continue  # carrera con otra solicitud idéntica: la transacción se revirtió y se relee
    raise ToolError("TICKET_NO_CREADO", "No se pudo crear el ticket de forma idempotente")


@herramienta
def actualizar_ticket(ticket_id: str, estado: str = "", transaccion_id: str = "", tipo_reclamo: str = "",
                      evento: str = "ACTUALIZACION", detalle_json: str = "{}", actor: str = "agente",
                      trace_id: str = "") -> dict[str, Any]:
    """Actualiza estado/transacción del ticket y registra el evento en el historial."""
    if estado and estado not in ESTADOS_TICKET:
        raise ToolError("ESTADO_INVALIDO", f"Estado no permitido: {estado}")
    with db.conexion() as cn:
        _ticket(cn, ticket_id)
        sets, params = ["actualizado_en = SYSUTCDATETIME()"], []
        for col, val in (("estado", estado), ("transaccion_id", transaccion_id), ("tipo_reclamo", tipo_reclamo)):
            if val:
                sets.append(f"{col} = ?")
                params.append(val)
        db.ejecutar(f"UPDATE Ticket SET {', '.join(sets)} WHERE ticket_id = ?", (*params, ticket_id), cn)
        _evento(cn, ticket_id, evento, json.loads(detalle_json or "{}"), actor, trace_id)
    return {"ticket_id": ticket_id, "estado": estado or None}


@herramienta
def registrar_evidencia(ticket_id: str, tipo: str, sha256: str, ruta: str, extraccion_json: str, valida: bool,
                        trace_id: str = "") -> dict[str, Any]:
    """Registra evidencia recibida (audio/imagen/texto) con su hash; idempotente por (ticket, sha256)."""
    with db.conexion() as cn:
        _ticket(cn, ticket_id)
        if not db.uno("SELECT 1 AS x FROM Evidencia WHERE ticket_id = ? AND sha256 = ?", (ticket_id, sha256), cn):
            db.ejecutar("INSERT INTO Evidencia (ticket_id, tipo, sha256, ruta, extraccion_json, valida) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (ticket_id, tipo, sha256, ruta, extraccion_json, int(valida)), cn)
    return {"ticket_id": ticket_id, "tipo": tipo}


@herramienta
def registrar_discrepancia(ticket_id: str, campo: str, percibido: str, maestro: str, accion: str,
                           trace_id: str = "") -> dict[str, Any]:
    """Una contradicción entre fuentes se REGISTRA (autoridad: dato maestro) y se escala; nunca se corrige sola."""
    with db.conexion() as cn:
        _ticket(cn, ticket_id)
        if not db.uno("SELECT 1 AS x FROM Discrepancia WHERE ticket_id = ? AND campo = ? AND valor_percepcion = ? "
                      "AND valor_maestro = ?", (ticket_id, campo, percibido, maestro), cn):
            db.ejecutar("INSERT INTO Discrepancia (ticket_id, campo, valor_percepcion, valor_maestro, accion) "
                        "VALUES (?, ?, ?, ?, ?)", (ticket_id, campo, percibido, maestro, accion), cn)
            _evento(cn, ticket_id, "DISCREPANCIA_REGISTRADA",
                    {"campo": campo, "percibido": percibido, "maestro": maestro}, "agente", trace_id)
    return {"ticket_id": ticket_id, "campo": campo}


@herramienta
def solicitar_aprobacion(ticket_id: str, accion: str, transaccion_id: str, monto: float, rol_requerido: str,
                         resumen_json: str, timeout_horas: float = 24.0, trace_id: str = "") -> dict[str, Any]:
    """Crea (o recupera) la solicitud de aprobación humana. Idempotente por (ticket, acción)."""
    aprobacion_id = "APR-" + hashlib.sha256(f"{ticket_id}|{accion}".encode()).hexdigest()[:10].upper()
    with db.conexion() as cn:
        _ticket(cn, ticket_id)
        ap = db.uno("SELECT * FROM AprobacionHitl WHERE aprobacion_id = ?", (aprobacion_id,), cn)
        if not ap:
            expira = _ahora() + timedelta(hours=timeout_horas)
            db.ejecutar(
                "INSERT INTO AprobacionHitl (aprobacion_id, ticket_id, accion_propuesta, transaccion_id, monto, "
                "rol_requerido, resumen_json, expira_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (aprobacion_id, ticket_id, accion, transaccion_id, monto, rol_requerido, resumen_json, expira), cn)
            db.ejecutar("UPDATE Ticket SET estado = 'PENDIENTE_APROBACION', actualizado_en = SYSUTCDATETIME() "
                        "WHERE ticket_id = ?", (ticket_id,), cn)
            _evento(cn, ticket_id, "APROBACION_SOLICITADA", {"accion": accion, "monto": monto, "rol": rol_requerido},
                    "agente", trace_id)
            ap = db.uno("SELECT * FROM AprobacionHitl WHERE aprobacion_id = ?", (aprobacion_id,), cn)
    return {**_fila(ap)}


def _exigir_aprobacion(cn: pyodbc.Connection, ticket_id: str, transaccion_id: str, aprobacion_id: str,
                       accion: str) -> dict:
    """Defensa en profundidad: la tool verifica en BD la aprobación; el grafo no es la única barrera."""
    ap = db.uno("SELECT * FROM AprobacionHitl WHERE aprobacion_id = ?", (aprobacion_id,), cn)
    if (not ap or ap["ticket_id"] != ticket_id or ap["accion_propuesta"] != accion
            or ap["transaccion_id"] != transaccion_id or ap["estado"] != "APROBADA"):
        raise ToolError("APROBACION_REQUERIDA", f"No existe una aprobación humana APROBADA para {accion}")
    return ap


def _reservar_accion(cn: pyodbc.Connection, ticket_id: str, accion: str, transaccion_id: str) -> bool:
    """Política P-05: una sola acción por reclamo. True si se reservó ahora, False si ya estaba hecha igual."""
    n = db.ejecutar("UPDATE Ticket SET accion_ejecutada = ?, transaccion_accion_id = ?, actualizado_en = "
                    "SYSUTCDATETIME() WHERE ticket_id = ? AND accion_ejecutada IS NULL",
                    (accion, transaccion_id, ticket_id), cn)
    if n == 1:
        return True
    t = _ticket(cn, ticket_id)
    if t["accion_ejecutada"] == accion and t["transaccion_accion_id"] == transaccion_id:
        return False
    raise ToolError("YA_ANULADA", "Solo se puede anular/reembolsar una transacción por reclamo (P-05)")


@herramienta
def anular_transaccion(ticket_id: str, transaccion_id: str, aprobacion_id: str,
                       trace_id: str = "") -> dict[str, Any]:
    """ACCIÓN PROTEGIDA (HITL): anula una operación aún no facturada y devuelve el disponible. Atómica."""
    with db.conexion() as cn:
        ap = _exigir_aprobacion(cn, ticket_id, transaccion_id, aprobacion_id, "ANULACION")
        if not _reservar_accion(cn, ticket_id, "ANULACION", transaccion_id):
            r = db.uno("SELECT reembolso_id FROM Reembolso WHERE ticket_id = ?", (ticket_id,), cn)
            return {"anulada": True, "ya_ejecutada": True, "reembolso_id": r["reembolso_id"] if r else None}
        tx = db.uno("SELECT t.monto, tr.cuenta_id FROM Transaccion t JOIN Tarjeta tr ON tr.tarjeta_id = t.tarjeta_id "
                    "WHERE t.transaccion_id = ?", (transaccion_id,), cn)
        if db.ejecutar("UPDATE Transaccion SET anulada = 1, estado = 'ANULADA', anulada_en = SYSUTCDATETIME() "
                       "WHERE transaccion_id = ? AND anulada = 0", (transaccion_id,), cn) == 0:
            raise ToolError("YA_ANULADA", "La transacción ya estaba anulada")
        if float(tx["monto"]) != float(ap["monto"]):
            raise ToolError("MONTO_NO_COINCIDE", "El monto aprobado no coincide con el dato maestro")
        db.ejecutar("UPDATE Balance SET saldo_disponible = saldo_disponible + ?, saldo = saldo - ?, "
                    "actualizado_en = SYSUTCDATETIME() WHERE cuenta_id = ?",
                    (float(tx["monto"]), float(tx["monto"]), tx["cuenta_id"]), cn)
        reembolso_id = "RMB-" + hashlib.sha256(f"{ticket_id}|ANULACION".encode()).hexdigest()[:10].upper()
        db.ejecutar("INSERT INTO Reembolso (reembolso_id, ticket_id, transaccion_id, tipo, monto, medio, estado, "
                    "sla_dias_habiles, fecha_estimada) VALUES (?, ?, ?, 'ANULACION', ?, 'REVERSA_INMEDIATA', "
                    "'PAGADO', 0, ?)", (reembolso_id, ticket_id, transaccion_id, float(tx["monto"]), _fecha_ref(cn)), cn)
        _evento(cn, ticket_id, "TRANSACCION_ANULADA", {"transaccion_id": transaccion_id, "monto": float(tx["monto"]),
                                                       "aprobacion_id": aprobacion_id}, "sistema", trace_id)
    return {"anulada": True, "ya_ejecutada": False, "reembolso_id": reembolso_id, "monto": float(tx["monto"])}


@herramienta
def registrar_reembolso(ticket_id: str, transaccion_id: str, aprobacion_id: str,
                        trace_id: str = "") -> dict[str, Any]:
    """ACCIÓN PROTEGIDA (HITL): programa el reembolso (7 días hábiles) de una operación ya facturada."""
    with db.conexion() as cn:
        ap = _exigir_aprobacion(cn, ticket_id, transaccion_id, aprobacion_id, "REEMBOLSO")
        tx = db.uno("SELECT t.monto, t.anulada, tr.habilitada FROM Transaccion t JOIN Tarjeta tr "
                    "ON tr.tarjeta_id = t.tarjeta_id WHERE t.transaccion_id = ?", (transaccion_id,), cn)
        if not tx["habilitada"]:
            raise ToolError("REQUIERE_OPERADOR", "La tarjeta no está habilitada: debe coordinar un operador (P-06)")
        if not _reservar_accion(cn, ticket_id, "REEMBOLSO", transaccion_id):
            r = db.uno("SELECT reembolso_id, fecha_estimada FROM Reembolso WHERE ticket_id = ?", (ticket_id,), cn)
            return {"reembolso_id": r["reembolso_id"], "ya_ejecutada": True, "fecha_estimada": _f(r["fecha_estimada"])}
        if float(tx["monto"]) != float(ap["monto"]):
            raise ToolError("MONTO_NO_COINCIDE", "El monto aprobado no coincide con el dato maestro")
        fecha_est = sumar_dias_habiles(_fecha_ref(cn), SLA_REEMBOLSO_DIAS_HABILES)
        reembolso_id = "RMB-" + hashlib.sha256(f"{ticket_id}|REEMBOLSO".encode()).hexdigest()[:10].upper()
        db.ejecutar("INSERT INTO Reembolso (reembolso_id, ticket_id, transaccion_id, tipo, monto, medio, estado, "
                    "sla_dias_habiles, fecha_estimada) VALUES (?, ?, ?, 'REEMBOLSO', ?, 'TARJETA_ORIGEN', "
                    "'PROGRAMADO', ?, ?)", (reembolso_id, ticket_id, transaccion_id, float(tx["monto"]),
                                            SLA_REEMBOLSO_DIAS_HABILES, fecha_est), cn)
        db.ejecutar("UPDATE Transaccion SET estado = 'REEMBOLSADA' WHERE transaccion_id = ?", (transaccion_id,), cn)
        _evento(cn, ticket_id, "REEMBOLSO_PROGRAMADO", {"transaccion_id": transaccion_id, "monto": float(tx["monto"]),
                                                        "fecha_estimada": fecha_est.isoformat()}, "sistema", trace_id)
    return {"reembolso_id": reembolso_id, "ya_ejecutada": False, "monto": float(tx["monto"]),
            "fecha_estimada": fecha_est.isoformat(), "sla_dias_habiles": SLA_REEMBOLSO_DIAS_HABILES}


@herramienta
def escalar_operador(ticket_id: str, motivo: str, resumen: str, trace_id: str = "") -> dict[str, Any]:
    """Escala a un operador por correo (patrón outbox: se persiste siempre; el SMTP es opcional)."""
    s = get_settings()
    asunto = f"[{ticket_id}] Escalamiento: {motivo[:80]}"
    with db.conexion() as cn:
        _ticket(cn, ticket_id)
        previo = db.uno("SELECT email_id, estado FROM EmailOutbox WHERE ticket_id = ? AND asunto = ?",
                        (ticket_id, asunto), cn)
        if previo:
            return {"email_id": previo["email_id"], "estado": previo["estado"], "repetido": True}
        db.ejecutar("INSERT INTO EmailOutbox (ticket_id, destino, asunto, cuerpo) VALUES (?, ?, ?, ?)",
                    (ticket_id, s.operador_email, asunto, resumen), cn)
        email = db.uno("SELECT MAX(email_id) AS id FROM EmailOutbox WHERE ticket_id = ?", (ticket_id,), cn)
        db.ejecutar("UPDATE Ticket SET estado = 'EN_ESCALAMIENTO', resolucion = 'ESCALADO', "
                    "actualizado_en = SYSUTCDATETIME() WHERE ticket_id = ?", (ticket_id,), cn)
        _evento(cn, ticket_id, "ESCALADO_A_OPERADOR", {"motivo": motivo, "destino": s.operador_email}, "agente",
                trace_id)
        estado = "PENDIENTE"
        if s.smtp_host:
            try:
                msg = EmailMessage()
                msg["From"], msg["To"], msg["Subject"] = "reclamos@ejemplo.test", s.operador_email, asunto
                msg.set_content(resumen)
                with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=3) as smtp:
                    smtp.send_message(msg)
                estado = "ENVIADO"
            except OSError:
                estado = "ERROR"
            db.ejecutar("UPDATE EmailOutbox SET estado = ?, enviado_en = CASE WHEN ? = 'ENVIADO' THEN "
                        "SYSUTCDATETIME() END WHERE email_id = ?", (estado, estado, email["id"]), cn)
    return {"email_id": email["id"], "estado": estado, "repetido": False}


@herramienta
def cerrar_ticket(ticket_id: str, resolucion: str, trace_id: str = "") -> dict[str, Any]:
    """Cierra el ticket (idempotente)."""
    if resolucion not in RESOLUCIONES:
        raise ToolError("RESOLUCION_INVALIDA", f"Resolución no permitida: {resolucion}")
    with db.conexion() as cn:
        t = _ticket(cn, ticket_id)
        if t["estado"] == "CERRADO":
            return {"ticket_id": ticket_id, "estado": "CERRADO", "resolucion": t["resolucion"], "ya_cerrado": True}
        db.ejecutar("UPDATE Ticket SET estado = 'CERRADO', resolucion = ?, cerrado_en = SYSUTCDATETIME(), "
                    "actualizado_en = SYSUTCDATETIME() WHERE ticket_id = ?", (resolucion, ticket_id), cn)
        _evento(cn, ticket_id, "TICKET_CERRADO", {"resolucion": resolucion}, "sistema", trace_id)
    return {"ticket_id": ticket_id, "estado": "CERRADO", "resolucion": resolucion, "ya_cerrado": False}
