import os
import json

# Silenciar logs de TensorFlow
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pysentimiento import create_analyzer
from pysentimiento.preprocessing import preprocess_tweet

# ── Inicializar app y modelo ──────────────────────────────────────────────────
app = FastAPI(title="API - Análisis Emocional TFG")

# CORS: permite que el frontend (abierto como archivo local o en otro puerto)
# pueda llamar a este servidor sin que el navegador lo bloquee.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # En producción, limitar al dominio real
    allow_methods=["POST"],
    allow_headers=["*"],
)

# El modelo se carga UNA sola vez al arrancar el servidor (tarda ~30 s)
print("Cargando modelo RoBERTuito... (esto puede tardar unos segundos)")
emotion_analyzer = create_analyzer(task="emotion", lang="es")
print("Modelo listo.")

# ── Pesos vectoriales del Modelo Circumplejo de Russell (Ekman) ───────────────
COORDENADAS_EKMAN = {
    "joy":      {"valencia":  0.81, "activacion":  0.51},
    "surprise": {"valencia":  0.40, "activacion":  0.67},
    "anger":    {"valencia": -0.51, "activacion":  0.59},
    "fear":     {"valencia": -0.64, "activacion":  0.60},
    "disgust":  {"valencia": -0.60, "activacion":  0.35},
    "sadness":  {"valencia": -0.63, "activacion": -0.27},
    "others":   {"valencia":  0.00, "activacion":  0.00},
}

# ── Modelos de datos (entrada / salida) ───────────────────────────────────────
class TextoEMA(BaseModel):
    respuesta_1: str   # ¿Qué estás haciendo?
    respuesta_2: str   # ¿Cómo te sientes?

class ResultadoAnalisis(BaseModel):
    valencia: float
    activacion: float
    emocion_dominante: str
    probabilidades: dict

# ── Endpoint principal ────────────────────────────────────────────────────────
@app.post("/api/analizar", response_model=ResultadoAnalisis)
async def analizar(payload: TextoEMA):
    # 1. Combinar y preprocesar
    texto_combinado = payload.respuesta_1 + " " + payload.respuesta_2
    texto_limpio = preprocess_tweet(texto_combinado)

    # 2. Inferencia con pysentimiento
    resultado = emotion_analyzer.predict(texto_limpio)

    # 3. Calcular centroide en el espacio circumplejo
    x_valencia = 0.0
    y_activacion = 0.0
    suma_pesos = 0.0

    for emocion, prob in resultado.probas.items():
        if emocion in COORDENADAS_EKMAN:
            x_valencia   += prob * COORDENADAS_EKMAN[emocion]["valencia"]
            y_activacion  += prob * COORDENADAS_EKMAN[emocion]["activacion"]
            suma_pesos    += prob

    if suma_pesos > 0:
        x_valencia   /= suma_pesos
        y_activacion /= suma_pesos

    # El gráfico Chart.js usa un rango -10..10; escalamos desde -1..1
    x_escalado = round(x_valencia   * 10, 4)
    y_escalado = round(y_activacion * 10, 4)

    return ResultadoAnalisis(
        valencia=x_escalado,
        activacion=y_escalado,
        emocion_dominante=resultado.output,
        probabilidades=resultado.probas,
    )

# ── Health check (opcional, útil para debugging) ─────────────────────────────
@app.get("/")
def root():
    return {"estado": "API activa", "modelo": "RoBERTuito (pysentimiento)"}
