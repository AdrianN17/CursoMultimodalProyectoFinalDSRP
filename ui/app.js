const API = "/api/v1";
const $ = (id) => document.getElementById(id);
const aviso = (msg, tipo = "") => { const a = $("aviso"); a.textContent = msg; a.className = tipo; };
const depurar = (obj) => { $("debug-json").textContent = JSON.stringify(obj, null, 2); };

async function llamar(url, opciones = {}) {
  const r = await fetch(url, opciones);
  const tipo = r.headers.get("content-type") || "";
  const cuerpo = tipo.includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error(cuerpo?.detail || `Error ${r.status}`);
  return cuerpo;
}

// ---------------------------------------------------------------- cliente
function iniciarCliente() {
  let sesionId = null, audioBlob = null, imagen = null, grabador = null, trozos = [];
  const habilitar = () => { $("btn-enviar").disabled = !(sesionId && (audioBlob) && imagen && $("otp").value.length >= 4); };

  $("btn-sesion").onclick = async () => {
    try {
      const s = await llamar(`${API}/sesiones`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      sesionId = s.sesion_id;
      $("otp-info").textContent = s.otp_demo
        ? `Sesión ${s.sesion_id}. Modo demo: su código es ${s.otp_demo}.`
        : `Sesión ${s.sesion_id}. Le enviamos un código a su correo registrado.`;
      aviso("Sesión iniciada", "ok"); habilitar();
    } catch (e) { aviso(e.message, "error"); }
  };

  $("btn-grabar").onclick = async () => {
    if (grabador && grabador.state === "recording") { grabador.stop(); return; }
    try {
      const flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
      trozos = []; grabador = new MediaRecorder(flujo);
      grabador.ondataavailable = (e) => trozos.push(e.data);
      grabador.onstop = () => {
        flujo.getTracks().forEach((t) => t.stop());
        audioBlob = new File([new Blob(trozos, { type: grabador.mimeType })], "relato.webm", { type: grabador.mimeType });
        $("previa-audio").src = URL.createObjectURL(audioBlob); $("previa-audio").hidden = false;
        $("btn-grabar").textContent = "● Grabar de nuevo"; $("estado-grab").textContent = "Grabación lista"; habilitar();
      };
      grabador.start(); $("btn-grabar").textContent = "■ Detener"; $("estado-grab").textContent = "Grabando…";
    } catch { aviso("No se pudo acceder al micrófono; suba un archivo de audio.", "error"); }
  };

  $("archivo-audio").onchange = (e) => {
    audioBlob = e.target.files[0] || null;
    if (audioBlob) { $("previa-audio").src = URL.createObjectURL(audioBlob); $("previa-audio").hidden = false; }
    habilitar();
  };
  $("archivo-imagen").onchange = (e) => {
    imagen = e.target.files[0] || null;
    if (imagen) { $("previa-imagen").src = URL.createObjectURL(imagen); $("previa-imagen").hidden = false; }
    habilitar();
  };
  $("otp").oninput = habilitar;

  $("btn-enviar").onclick = async () => {
    const fd = new FormData();
    fd.append("sesion_id", sesionId); fd.append("otp", $("otp").value);
    fd.append("audio", audioBlob); fd.append("imagen", imagen);
    if ($("texto").value.trim()) fd.append("texto", $("texto").value.trim());
    $("btn-enviar").disabled = true; aviso("Procesando su reclamo…");
    try {
      const r = await llamar(`${API}/reclamos`, { method: "POST", body: fd, headers: { "Idempotency-Key": crypto.randomUUID() } });
      depurar(r);
      if (r.audio_url) {
        $("respuesta").hidden = false;
        const p = $("audio-respuesta"); p.src = r.audio_url; p.play().catch(() => {});
      }
      aviso(r.pendiente_hitl ? "Su caso fue enviado a revisión." : "Respuesta lista.", "ok");
    } catch (e) { aviso(e.message, "error"); }
    habilitar();
  };
}

// ---------------------------------------------------------------- analista
function iniciarAnalista() {
  const cabeceras = () => ({ "X-Analista-Key": $("clave").value, "Content-Type": "application/json" });

  async function cargar() {
    try {
      const filas = await llamar(`${API}/aprobaciones`, { headers: cabeceras() });
      const lista = $("lista"); lista.replaceChildren();
      if (!filas.length) lista.textContent = "No hay aprobaciones pendientes.";
      filas.forEach((f) => lista.appendChild(tarjeta(f)));
      aviso("", "");
    } catch (e) { aviso(e.message, "error"); }
  }

  function tarjeta(f) {
    const d = document.createElement("div"); d.className = "tarjeta";
    const t = document.createElement("div");
    t.textContent = `${f.accion_propuesta} · ticket ${f.ticket_id} · S/ ${f.monto} · rol requerido: ${f.rol_requerido} · vence ${f.expira_en}`;
    const pre = document.createElement("pre"); pre.textContent = JSON.stringify(f.resumen, null, 2);
    const motivo = document.createElement("input"); motivo.placeholder = "Motivo (obligatorio)"; motivo.style.width = "100%";
    const acciones = document.createElement("div"); acciones.className = "acciones";
    for (const decision of ["APROBADA", "RECHAZADA"]) {
      const b = document.createElement("button"); b.textContent = decision === "APROBADA" ? "Aprobar" : "Rechazar";
      b.onclick = async () => {
        if (motivo.value.trim().length < 3) { aviso("Escriba un motivo", "error"); return; }
        b.disabled = true;
        try {
          const r = await llamar(`${API}/aprobaciones/${f.aprobacion_id}/decision`, {
            method: "POST", headers: cabeceras(),
            body: JSON.stringify({ decision, motivo: motivo.value, aprobador: $("aprobador").value, rol: $("rol").value }),
          });
          depurar(r); aviso(`Decisión registrada: ${decision}`, "ok"); cargar();
        } catch (e) { aviso(e.message, "error"); b.disabled = false; }
      };
      acciones.appendChild(b);
    }
    d.append(t, pre, motivo, acciones);
    return d;
  }

  $("btn-refrescar").onclick = cargar; cargar();
}
