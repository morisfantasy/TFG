import os
import json

# Limpieza de logs de la consola
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

from pysentimiento import create_analyzer
from pysentimiento.preprocessing import preprocess_tweet

# 1. Inicializar modelo RoBERTuito
emotion_analyzer = create_analyzer(task="emotion", lang="es")

# 2. Datos del paciente
pregunta_1 = "¿Qué estás haciendo?"
respuesta_1 = "Nada"
pregunta_2 = "¿Qué tal estás?"
respuesta_2 = "Normal"

# 3. Combinar texto
texto_diario = respuesta_1 + " " + respuesta_2
texto_limpio = preprocess_tweet(texto_diario)

# 4. Inferencia
resultado = emotion_analyzer.predict(texto_limpio)

# 5. Estrucutra JSON
datos_a_guardar = {
    "texto_original": texto_diario,
    "texto_preprocesado": texto_limpio,
    "emocion_dominante": resultado.output,
    "probabilidades": resultado.probas
}

archivo_json = "emociones_resultado.json"
with open(archivo_json, "w", encoding="utf-8") as f:
    json.dump(datos_a_guardar, f, ensure_ascii=False, indent=4)

print(f"--- SCRIPT 1 FINALIZADO ---")
print(f"Los resultados de Ekman se han guardado con éxito en '{archivo_json}'\n")