import json
import matplotlib.pyplot as plt

# 1. Cargar el JSON generado por el primer script
archivo_json = "emociones_resultado.json"

try:
    with open(archivo_json, "r", encoding="utf-8") as f:
        datos_usuario = json.load(f)
except FileNotFoundError:
    print(f"Error: No se encontró el archivo '{archivo_json}'. Ejecuta primero el Script 1.")
    exit()

probabilidades = datos_usuario["probabilidades"]

# 2. Definición del diccionario de pesos vectoriales
coordenadas_ekman = {
    "joy": {"valencia": 0.81, "activacion": 0.51}, 
"surprise": {"valencia": 0.40, "activacion": 0.67}, 
"anger": {"valencia": -0.51, "activacion": 0.59}, 
"fear": {"valencia": -0.64, "activacion": 0.60}, 
"disgust": {"valencia": -0.60, "activacion": 0.35}, 
"sadness": {"valencia": -0.63, "activacion": -0.27}, 
"others": {"valencia": 0.00, "activacion": 0.00},
}

# 3. Calcular Centroide
x_final_valencia = 0.0
y_final_activacion = 0.0
suma_pesos = 0.0

for emocion, probabilidad in probabilidades.items():
    if emocion in coordenadas_ekman:
        x_final_valencia += probabilidad * coordenadas_ekman[emocion]["valencia"]
        y_final_activacion += probabilidad * coordenadas_ekman[emocion]["activacion"]
        suma_pesos += probabilidad

if suma_pesos > 0:
    x_final_valencia /= suma_pesos
    y_final_activacion /= suma_pesos

# 4. Mostrar resultados por consola
print("=== ANÁLISIS DE SEGUIMIENTO DIARIO ===")
print(f"Texto analizado: '{datos_usuario['texto_original']}'")
print(f"Coordenadas: X={x_final_valencia:.4f}, Y={y_final_activacion:.4f}\n")

# ==========================================
# 5. GRAFICAR CON MATPLOTLIB
# ==========================================

# Crear la figura, ejes y limites
fig, ax = plt.subplots(figsize=(8, 8))
ax.set_xlim(-1.1, 1.1)
ax.set_ylim(-1.1, 1.1)
ax.axhline(0, color='black', linewidth=1.5, zorder=1) # Eje X (Valencia)
ax.axvline(0, color='black', linewidth=1.5, zorder=1) # Eje Y (Activación)

#Fondo cuadricula
ax.grid(color='gray', linestyle='--', linewidth=0.5, alpha=0.5, zorder=0)

# Etiquetas de los ejes
ax.set_xlabel("VALENCIA (Negativa <---  ---> Positiva)", fontsize=12, fontweight='bold')
ax.set_ylabel("ACTIVACIÓN (Baja <---  ---> Alta)", fontsize=12, fontweight='bold')
ax.set_title("Estado del Paciente - Modelo Circunflejo de Russell", fontsize=14, pad=20)

# Textos de los cuadrantes(Hablar con Eva)
ax.text(0.5, 0.5, 'Alerta Positiva', color='green', alpha=0.3, ha='center', va='center', fontsize=12)
ax.text(-0.5, 0.5, 'Estrés / Tensión', color='red', alpha=0.3, ha='center', va='center', fontsize=12)
ax.text(-0.5, -0.5, 'Tristeza / Depresión', color='blue', alpha=0.3, ha='center', va='center', fontsize=12)
ax.text(0.5, -0.5, 'Calma / Relajación', color='purple', alpha=0.3, ha='center', va='center', fontsize=12)

# Punto usuario
ax.scatter(x_final_valencia, y_final_activacion, color='darkorange', s=150, edgecolor='black', zorder=5, label='Estado Actual')
ax.annotate('  Paciente', (x_final_valencia, y_final_activacion), fontsize=11, fontweight='bold')
ax.legend(loc='upper right')
plt.show()