import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt

# Silenciar logs de TensorFlow
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pysentimiento import create_analyzer
from pysentimiento.preprocessing import preprocess_tweet

# ── Configuración de Base de Datos ────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

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
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO usuarios (nombre_usuario, password_hash, edad, sexo) VALUES (%s, %s, %s, %s) RETURNING id, nombre_usuario",
            (user.nombre_usuario, hashed_password, user.edad, user.sexo)
        )
        res = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        return {"mensaje": "Usuario creado", "usuario_id": res['id'], "nombre_usuario": res['nombre_usuario']}
    except psycopg2.IntegrityError:
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/login")
def login_usuario(user: UsuarioLogin):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre_usuario, password_hash FROM usuarios WHERE nombre_usuario = %s", (user.nombre_usuario,))
    db_user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not db_user or not bcrypt.checkpw(user.password.encode('utf-8'), db_user['password_hash'].encode('utf-8')):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    
    return {"mensaje": "Login exitoso", "usuario_id": db_user['id'], "nombre_usuario": db_user['nombre_usuario']}

# ── Endpoint principal de Análisis ────────────────────────────────────────────
@app.post("/api/analizar")
async def analizar(payload: TextoEMA):
    # CAMBIO SOLICITADO: El modelo solo analizará la respuesta_2 (¿cómo estás?), la respuesta_1 se guarda pero NO se analiza.
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

@app.get("/")
def root():
    return {"estado": "API activa con Base de Datos"}