import os
import json
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt

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

# ── Configuración de Email (variables de entorno en Railway) ──────────────────
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER")      # tu correo remitente
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")  # contraseña de app de Gmail
APP_URL        = os.getenv("APP_URL", "https://tfg-production-db76.up.railway.app")

def enviar_email_verificacion(email_destino: str, token: str, nombre: str):
    enlace = f"{APP_URL}/api/verificar-email?token={token}"

    print(f"[EMAIL] Intentando enviar a: {email_destino}")
    print(f"[EMAIL] SMTP_HOST={SMTP_HOST} SMTP_PORT={SMTP_PORT}")
    print(f"[EMAIL] SMTP_USER={SMTP_USER}")
    print(f"[EMAIL] SMTP_PASSWORD configurado: {'SÍ' if SMTP_PASSWORD else 'NO — FALTA LA VARIABLE'}")
    print(f"[EMAIL] Enlace de verificación: {enlace}")

    if not SMTP_USER or not SMTP_PASSWORD:
        print("[EMAIL] ERROR: Faltan variables de entorno SMTP_USER o SMTP_PASSWORD. No se envía el correo.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Confirma tu cuenta en Alto y Claro"
    msg["From"]    = SMTP_USER
    msg["To"]      = email_destino

    html = f"""
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
    </body></html>
    """
    msg.attach(MIMEText(html, "html"))

    try:
        print("[EMAIL] Conectando al servidor SMTP...")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.set_debuglevel(1)   # muestra toda la conversación SMTP en los logs
            server.ehlo()
            server.starttls()
            server.ehlo()
            print("[EMAIL] Haciendo login...")
            server.login(SMTP_USER, SMTP_PASSWORD)
            print("[EMAIL] Login OK. Enviando mensaje...")
            server.sendmail(SMTP_USER, email_destino, msg.as_string())
            print(f"[EMAIL] ✅ Correo enviado correctamente a {email_destino}")
    except smtplib.SMTPAuthenticationError as e:
        print(f"[EMAIL] ❌ Error de autenticación SMTP: {e}")
        print("[EMAIL] Posibles causas:")
        print("[EMAIL]   1. La contraseña de aplicación es incorrecta")
        print("[EMAIL]   2. La cuenta de la UIE no permite contraseñas de aplicación")
        print("[EMAIL]   3. La verificación en dos pasos no está activada")
    except smtplib.SMTPConnectError as e:
        print(f"[EMAIL] ❌ No se pudo conectar al servidor SMTP: {e}")
    except Exception as e:
        print(f"[EMAIL] ❌ Error inesperado enviando email: {type(e).__name__}: {e}")

# ── Inicializar app y modelo ──────────────────────────────────────────────────
app = FastAPI(title="API - Análisis Emocional TFG")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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

    return {
        "valencia": x_escalado,
        "activacion": y_escalado,
        "emocion_dominante": emocion_dom,
        "respuesta_1": payload.respuesta_1
    }

# ── Endpoint para obtener el historial del usuario ─────────────────────────────
@app.get("/api/historial/{usuario_id}")
def obtener_historial(usuario_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT TO_CHAR(fecha_respuesta, 'DD/MM/YYYY') as fecha, 
                      valencia as x, activacion as y, emocion_dominante as emocion, respuesta_1 
               FROM registros_ema 
               WHERE usuario_id = %s 
               ORDER BY fecha_respuesta ASC""", 
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

# ── Servir la interfaz gráfica ─────────────────────────────────────────────────
@app.get("/")
def root():
    # Cuando alguien entre a la URL principal, le mostramos el HTML de la app
    return FileResponse("frontend.html")