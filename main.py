import os
import json
import secrets
import random
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
import pytz
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
from apscheduler.schedulers.background import BackgroundScheduler

# Silenciar logs de TensorFlow
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pysentimiento import create_analyzer
from pysentimiento.preprocessing import preprocess_tweet

# ── Configuración de Base de Datos ────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# ── Configuración de Email (SendGrid API) ────────────────────────────────────
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM    = os.getenv("SMTP_USER", "maurosanromancostas@gmail.com")
APP_URL          = os.getenv("APP_URL", "https://tfg-production-db76.up.railway.app")

def enviar_email_verificacion(email_destino: str, token: str, nombre: str):
    enlace = f"{APP_URL}/api/verificar-email?token={token}"

    print(f"[EMAIL] Intentando enviar a: {email_destino}")
    print(f"[EMAIL] SendGrid FROM: {SENDGRID_FROM}")
    print(f"[EMAIL] API Key configurada: {'SÍ' if SENDGRID_API_KEY else 'NO — FALTA SENDGRID_API_KEY'}")
    print(f"[EMAIL] Enlace: {enlace}")

    if not SENDGRID_API_KEY:
        print("[EMAIL] ERROR: Falta la variable SENDGRID_API_KEY.")
        return

    payload = json.dumps({
        "personalizations": [{"to": [{"email": email_destino}]}],
        "from": {"email": SENDGRID_FROM, "name": "Alto y Claro"},
        "subject": "Confirma tu cuenta en Alto y Claro",
        "content": [{
            "type": "text/html",
            "value": f"""
            <html><body style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
              <h2 style="color:#7BA098;">¡Bienvenido a Alto y Claro, {nombre}!</h2>
              <p>Gracias por registrarte. Para activar tu cuenta haz clic en el botón:</p>
              <a href="{enlace}" style="display:inline-block;margin:16px 0;padding:14px 28px;
                 background:#7BA098;color:white;text-decoration:none;border-radius:24px;
                 font-weight:bold;">Verificar mi cuenta</a>
              <p style="color:#64748B;font-size:13px;">
                Si no te has registrado en esta aplicación, ignora este correo.<br>
                El enlace caduca en 24 horas.
              </p>
            </body></html>"""
        }]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={
            "Authorization": f"Bearer {SENDGRID_API_KEY}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[EMAIL] ✅ Correo enviado. Status: {resp.status}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"[EMAIL] ❌ SendGrid HTTP error {e.code}: {body}")
    except Exception as e:
        print(f"[EMAIL] ❌ Error inesperado: {type(e).__name__}: {e}")


# ── Configuración FCM (Firebase Cloud Messaging API V1) ──────────────────────
# Credenciales de cuenta de servicio Firebase (cargadas desde variable de entorno)
FIREBASE_CREDENTIALS = json.loads(os.getenv("FIREBASE_CREDENTIALS", "{}"))
FIREBASE_PROJECT_ID  = FIREBASE_CREDENTIALS.get("project_id", "altoyclaro-tfg")

def obtener_access_token_fcm():
    """Obtiene un OAuth2 access token para la API FCM V1 usando JWT firmado con RSA."""
    import time
    import base64
    import hmac
    import hashlib

    creds = FIREBASE_CREDENTIALS
    if not creds:
        print("[FCM] FIREBASE_CREDENTIALS no configurado.")
        return None

    # Header y claims del JWT
    now = int(time.time())
    header  = base64.urlsafe_b64encode(json.dumps({"alg":"RS256","typ":"JWT"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps({
        "iss":   creds["client_email"],
        "sub":   creds["client_email"],
        "aud":   "https://oauth2.googleapis.com/token",
        "iat":   now,
        "exp":   now + 3600,
        "scope": "https://www.googleapis.com/auth/firebase.messaging"
    }).encode()).rstrip(b"=")

    signing_input = header + b"." + payload

    # Firmar con la clave privada RSA usando cryptography
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        private_key = serialization.load_pem_private_key(
            creds["private_key"].encode(), password=None
        )
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")
        jwt_token = (signing_input + b"." + sig_b64).decode()
    except Exception as e:
        print(f"[FCM] Error firmando JWT: {e}")
        return None

    # Intercambiar JWT por access token
    token_payload = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion":  jwt_token
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=token_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("access_token")
    except Exception as e:
        print(f"[FCM] Error obteniendo access token: {e}")
        return None

def enviar_push_fcm(fcm_token, titulo, cuerpo):
    if not fcm_token:
        print("[FCM] Sin token FCM.")
        return

    access_token = obtener_access_token_fcm()
    if not access_token:
        print("[FCM] No se pudo obtener access token.")
        return

    payload = json.dumps({
        "message": {
            "token": fcm_token,
            "notification": {"title": titulo, "body": cuerpo},
            "android": {"priority": "high"},
            "apns": {"headers": {"apns-priority": "10"}},
            "data": {"tipo": "ema_diario"}
        }
    }).encode("utf-8")

    url = f"https://fcm.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/messages:send"
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[FCM] Push enviado OK: {resp.read().decode()}")
    except urllib.error.HTTPError as e:
        print(f"[FCM] HTTP error {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"[FCM] Error: {type(e).__name__}: {e}")

def programar_ventanas_diarias():
    print("[SCHEDULER] Programando ventanas diarias...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, nombre_usuario, fcm_token, region FROM usuarios WHERE email_verificado = TRUE")
        usuarios = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[SCHEDULER] Error obteniendo usuarios: {e}")
        return

    for u in usuarios:
        usuario_id = u["id"]
        nombre     = u["nombre_usuario"]
        fcm_token  = u["fcm_token"]
        tz_str     = u["region"] or "Europe/Madrid"
        try:
            tz = pytz.timezone(tz_str)
        except Exception:
            tz = pytz.timezone("Europe/Madrid")

        hora_random   = random.randint(8, 22)
        minuto_random = random.randint(0, 59)
        hoy_local = datetime.now(tz).date()
        dt_local  = tz.localize(datetime(hoy_local.year, hoy_local.month, hoy_local.day, hora_random, minuto_random, 0))
        dt_utc    = dt_local.astimezone(pytz.utc)
        dt_cierre = dt_utc + timedelta(minutes=30)

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO ventanas_diarias (usuario_id, fecha, hora_notificacion, hora_cierre, respondida) VALUES (%s, %s, %s, %s, FALSE) ON CONFLICT (usuario_id, fecha) DO NOTHING",
                (usuario_id, hoy_local, dt_utc, dt_cierre)
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"[SCHEDULER] Error insertando ventana para {nombre}: {e}")
            continue

        delay = (dt_utc - datetime.now(pytz.utc)).total_seconds()
        if delay > 0 and fcm_token:
            scheduler.add_job(
                enviar_push_fcm, "date", run_date=dt_utc,
                args=[fcm_token, "Alto y Claro", "Tomaté un momento. Como estas ahora mismo?"],
                id=f"push_{usuario_id}_{hoy_local}", replace_existing=True
            )
            print(f"[SCHEDULER] Push para {nombre} a las {dt_local.strftime('%H:%M')} ({tz_str})")
        else:
            print(f"[SCHEDULER] {nombre}: ventana ya pasada o sin token")

    print("[SCHEDULER] Programacion completada.")

# ── Inicializar app y modelo ──────────────────────────────────────────────────
app = FastAPI(title="API - Análisis Emocional TFG")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

scheduler = BackgroundScheduler(timezone=pytz.utc)
scheduler.add_job(programar_ventanas_diarias, "cron", hour=0, minute=0, id="prog_diario")
scheduler.add_job(programar_ventanas_diarias, "date", run_date=datetime.now(pytz.utc) + timedelta(seconds=30), id="prog_arranque")
scheduler.start()
print("[SCHEDULER] Scheduler iniciado.")

print("Cargando modelo RoBERTuito... (esto puede tardar unos segundos)")
emotion_analyzer = create_analyzer(task="emotion", lang="es")
print("Modelo listo.")

COORDENADAS_EKMAN = {
    "joy":      {"valencia":  0.81, "activacion":  0.51},
    "surprise": {"valencia":  0.40, "activacion":  0.67},
    "anger":    {"valencia": -0.51, "activacion":  0.59},
    "fear":     {"valencia": -0.64, "activacion":  0.60},
    "disgust":  {"valencia": -0.60, "activacion":  0.35},
    "sadness":  {"valencia": -0.63, "activacion": -0.27},
    "others":   {"valencia":  0.00, "activacion":  0.00},
}

# ── Modelos de datos ──────────────────────────────────────────────────────────
class FcmToken(BaseModel):
    usuario_id: int
    fcm_token:  str

class UsuarioRegistro(BaseModel):
    nombre_usuario: str
    password: str
    edad: int
    sexo: str
    email: str = ""
    region: str = ""
    objetivo: str = ""

class Valoracion(BaseModel):
    usuario_id: int
    valoracion: str

class UsuarioLogin(BaseModel):
    nombre_usuario: str
    password: str

class TextoEMA(BaseModel):
    usuario_id: int
    respuesta_1: str
    respuesta_2: str

# ── Endpoints de Autenticación ────────────────────────────────────────────────
@app.post("/api/registro")
def registrar_usuario(user: UsuarioRegistro):
    hashed_password = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    token_verificacion = secrets.token_urlsafe(32)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO usuarios
               (nombre_usuario, password_hash, edad, sexo, email, region, objetivo,
                email_verificado, token_verificacion)
               VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, %s)
               RETURNING id, nombre_usuario""",
            (user.nombre_usuario, hashed_password, user.edad, user.sexo,
             user.email, user.region, user.objetivo, token_verificacion)
        )
        res = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        # Enviar correo de verificación
        enviar_email_verificacion(user.email, token_verificacion, user.nombre_usuario)
        return {
            "mensaje": "Usuario creado. Revisa tu correo para verificar la cuenta.",
            "usuario_id": res['id'],
            "nombre_usuario": res['nombre_usuario']
        }
    except psycopg2.IntegrityError:
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/login")
def login_usuario(user: UsuarioLogin):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, nombre_usuario, password_hash, email_verificado FROM usuarios WHERE nombre_usuario = %s",
        (user.nombre_usuario,)
    )
    db_user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not db_user or not bcrypt.checkpw(user.password.encode('utf-8'), db_user['password_hash'].encode('utf-8')):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    if not db_user['email_verificado']:
        raise HTTPException(status_code=403, detail="Cuenta sin verificar. Revisa tu correo y confirma tu cuenta antes de entrar.")

    return {"mensaje": "Login exitoso", "usuario_id": db_user['id'], "nombre_usuario": db_user['nombre_usuario']}

# ── Endpoint principal de Análisis ────────────────────────────────────────────
@app.post("/api/analizar")
async def analizar(payload: TextoEMA):
    # El modelo solo analizará la respuesta_2 (¿cómo estás?), la respuesta_1 se guarda pero NO se analiza.
    texto_limpio = preprocess_tweet(payload.respuesta_2)
    resultado = emotion_analyzer.predict(texto_limpio)

    x_valencia, y_activacion, suma_pesos = 0.0, 0.0, 0.0

    for emocion, prob in resultado.probas.items():
        if emocion in COORDENADAS_EKMAN:
            x_valencia   += prob * COORDENADAS_EKMAN[emocion]["valencia"]
            y_activacion += prob * COORDENADAS_EKMAN[emocion]["activacion"]
            suma_pesos   += prob

    if suma_pesos > 0:
        x_valencia /= suma_pesos
        y_activacion /= suma_pesos

    x_escalado = round(x_valencia * 10, 4)
    y_escalado = round(y_activacion * 10, 4)
    emocion_dom = resultado.output

    # Guardar en Base de Datos
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO registros_ema 
               (usuario_id, respuesta_1, respuesta_2, emocion_dominante, valencia, activacion) 
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (payload.usuario_id, payload.respuesta_1, payload.respuesta_2, emocion_dom, x_escalado, y_escalado)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print("Error guardando en DB:", e)

    marcar_ventana_respondida(payload.usuario_id)

    alerta_activa = detectar_riesgo_emocional(payload.usuario_id)

    return {
        "valencia": x_escalado,
        "activacion": y_escalado,
        "emocion_dominante": emocion_dom,
        "respuesta_1": payload.respuesta_1,
        "alerta_emergencia": alerta_activa
    }

# ── Endpoint para obtener el historial del usuario ─────────────────────────────
@app.get("/api/historial/{usuario_id}")
def obtener_historial(usuario_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT DISTINCT ON (DATE(fecha_respuesta))
                      TO_CHAR(fecha_respuesta, 'DD/MM/YYYY') as fecha,
                      valencia as x, activacion as y, emocion_dominante as emocion, respuesta_1
               FROM registros_ema
               WHERE usuario_id = %s
               ORDER BY DATE(fecha_respuesta) ASC, fecha_respuesta DESC""",
            (usuario_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Endpoint de Valoración ────────────────────────────────────────────────────
@app.post("/api/valoracion")
def guardar_valoracion(payload: Valoracion):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE usuarios SET valoracion = %s WHERE id = %s",
            (payload.valoracion, payload.usuario_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return {"mensaje": "Valoración guardada correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Endpoint verificación de email ───────────────────────────────────────────
@app.get("/api/verificar-email")
def verificar_email(token: str):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM usuarios WHERE token_verificacion = %s AND email_verificado = FALSE",
            (token,)
        )
        usuario = cursor.fetchone()
        if not usuario:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=400, detail="Enlace de verificación inválido o ya utilizado.")

        cursor.execute(
            "UPDATE usuarios SET email_verificado = TRUE, token_verificacion = NULL WHERE id = %s",
            (usuario['id'],)
        )
        conn.commit()
        cursor.close()
        conn.close()
        # Redirigir al usuario a la app con mensaje de éxito
        html = """<!DOCTYPE html>
        <html><head><meta charset="UTF-8">
        <meta http-equiv="refresh" content="3;url=/">
        <style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;
        height:100vh;margin:0;background:#F0F4F3;}
        .box{text-align:center;padding:40px;background:white;border-radius:20px;box-shadow:0 4px 20px rgba(0,0,0,.08);}
        h2{color:#7BA098;}p{color:#64748B;}</style></head>
        <body><div class="box">
          <h2>✅ ¡Cuenta verificada!</h2>
          <p>Tu cuenta ha sido activada correctamente.<br>Serás redirigido a la aplicación en 3 segundos...</p>
        </div></body></html>"""
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Endpoint: comprobar estado de verificación (polling del cliente) ─────────
@app.get("/api/estado-verificacion/{usuario_id}")
def estado_verificacion(usuario_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT email_verificado, nombre_usuario FROM usuarios WHERE id = %s",
            (usuario_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return {"verificado": row['email_verificado'], "nombre_usuario": row['nombre_usuario']}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Endpoint: reenviar correo de verificación ─────────────────────────────────
class ReenvioVerificacion(BaseModel):
    email: str

@app.post("/api/reenviar-verificacion")
def reenviar_verificacion(payload: ReenvioVerificacion):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, nombre_usuario, token_verificacion, email_verificado FROM usuarios WHERE email = %s",
            (payload.email,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No existe ninguna cuenta con ese correo.")
        if row['email_verificado']:
            raise HTTPException(status_code=400, detail="Esta cuenta ya está verificada.")

        # Generar nuevo token
        nuevo_token = secrets.token_urlsafe(32)
        cursor.execute(
            "UPDATE usuarios SET token_verificacion = %s WHERE id = %s",
            (nuevo_token, row['id'])
        )
        conn.commit()
        cursor.close()
        conn.close()
        enviar_email_verificacion(payload.email, nuevo_token, row['nombre_usuario'])
        return {"mensaje": "Correo de verificación reenviado."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Detector de riesgo emocional sostenido ───────────────────────────────────
def detectar_riesgo_emocional(usuario_id: int) -> bool:
    """
    Devuelve True si los últimos 5 registros tienen una media de valencia <= -5.0.
    Umbral basado en el cuadrante de tristeza/letargo del modelo circumplejo de Russell.
    Referencia: afecto negativo de baja activación sostenido durante varios días
    es el indicador más consistente de episodio depresivo en estudios EMA
    (Trull et al., 2008; Barge-Schaapveld et al., 1999).
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT valencia FROM registros_ema
               WHERE usuario_id = %s
               ORDER BY fecha_respuesta DESC
               LIMIT 5""",
            (usuario_id,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if len(rows) < 5:
            return False  # No hay suficientes datos aún

        media_valencia = sum(float(r['valencia']) for r in rows) / len(rows)
        print(f"[ALERTA] Usuario {usuario_id} — media valencia últimos 5 registros: {media_valencia:.2f}")

        return media_valencia <= -5.0

    except Exception as e:
        print(f"[ALERTA] Error en detección de riesgo: {e}")
        return False

# ── Endpoint: guardar token FCM ───────────────────────────────────────────────
@app.post("/api/fcm-token")
def guardar_fcm_token(payload: FcmToken):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET fcm_token = %s WHERE id = %s", (payload.fcm_token, payload.usuario_id))
        conn.commit()
        cursor.close()
        conn.close()
        return {"mensaje": "Token FCM guardado."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Endpoint: estado ventana diaria ──────────────────────────────────────────
@app.get("/api/ventana/{usuario_id}")
def obtener_ventana(usuario_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT v.hora_notificacion, v.hora_cierre, v.respondida FROM ventanas_diarias v WHERE v.usuario_id = %s AND v.fecha = CURRENT_DATE",
            (usuario_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            return {"estado": "sin_ventana"}

        ahora       = datetime.now(pytz.utc)
        hora_notif  = row["hora_notificacion"]
        hora_cierre = row["hora_cierre"]
        if hora_notif.tzinfo is None:
            hora_notif  = pytz.utc.localize(hora_notif)
        if hora_cierre.tzinfo is None:
            hora_cierre = pytz.utc.localize(hora_cierre)

        if row["respondida"]:
            return {"estado": "respondida"}
        if ahora < hora_notif:
            return {"estado": "pendiente", "hora_notificacion": hora_notif.isoformat()}
        if hora_notif <= ahora <= hora_cierre:
            segundos = int((hora_cierre - ahora).total_seconds())
            return {"estado": "abierta", "segundos_restantes": segundos}
        return {"estado": "cerrada"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def marcar_ventana_respondida(usuario_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE ventanas_diarias SET respondida = TRUE WHERE usuario_id = %s AND fecha = CURRENT_DATE",
            (usuario_id,)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[VENTANA] Error: {e}")

# ── Servir la interfaz gráfica ─────────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse("frontend.html")

@app.get("/firebase-messaging-sw.js")
def service_worker():
    return FileResponse("firebase-messaging-sw.js", media_type="application/javascript")