"""
forzar_notificacion.py
──────────────────────
Script para forzar el envío de una notificación push y abrir la ventana EMA
de 30 minutos para un usuario concreto. Úsalo desde VS Code para la demo.

Uso:
    python forzar_notificacion.py

Requisitos:
    pip install requests cryptography pytz psycopg2-binary
"""

import os
import json
import time
import base64
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta
import pytz
import psycopg2
from psycopg2.extras import RealDictCursor

# ── CONFIGURACIÓN ─────────────────────────────────────────────────────────────
# Copia aquí los mismos valores que tienes en Railway

DATABASE_URL = "postgresql://postgres:tiemIIuXFeyYlyPymQMibMCfkeJebpwI@thomas.proxy.rlwy.net:15866/railway"  # ← cambia esto

FIREBASE_CREDENTIALS = {
    "type": "service_account",
    "project_id": "altoyclaro-tfg",
    "private_key_id": "00528604a5955faa3b12bf465f09dc289a755702",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCeYneLVrzlBacZ\nSG0FC2PmQbRw0HhPjP+9F/YkDOdze5p5epdaWmTgnNqb3lIAX7hu2/UIdIHN+plT\nr2yUBuVkf7KZ7hD/nl6+pZeaU2H35X8Nv4+jjHKgxSfX2iIQ88rBfrdsnNT85u9E\n1rYaKqoyDmXjzdblqYpDSsztqqZ0qIemwcEpZAuCLqHtUmsajhNqHVbmupM/DhVy\nIPwBxi6EGiz0Z+4fkqRmF3xJbH0mlU/MuxfeGIKpGoy3xfniEyClBh8ud93ASqY6\n3cI32EhOjteFJMhJZtQOJXrcSoqmEIG4xEaxoSVYtETMgjGNVBweccQhrsrh6xXt\n1sHJ3MNZAgMBAAECggEAIwFHQ4wJlqJ/snZP5ggE7cyCyVZB6O8UTKIhnAkgFGVy\nmDuwfN8yoXP5Wu6xd/Sv6gyCJPq+/5vNzHGekT7O7z3L5vp3Vk+VyBQIJCseoW/e\n+1ZltDNj2EWKz0meMtn263oKpx4ocrbFlhTQTYs1b3fALC9/ueWVMdcz4KlRPcHy\np7jjOGrYR6SQ9zOqDNlo3RMxhsQA8zrcGsuzieMKUbqRU4uWWP4dreUfFC3K3Dbf\nDGMQP8VsPzDwYDkqL0yDzL9SkOq952pSo5SDOC/oWNJ0NZOK/mVyFMWcqeqRRP6o\ntvm30NoNa3T44s1N4UBHZq/g7VM+ccQIbWcVu0sTyQKBgQDM3fX076/c4AamdWer\ny+6pOpLLCksh9ZnpKv7JM3aA0wf2JY4GyRi7uFrIyHKkKamsX07VG64Ls94Ot3yc\nPqLpAULBJ47jaBNdHlREm8wKQ8cPeXugdVDv/QAEtkYQ2fVjbCus379ndkR3ya4I\nUKpF7w8WUlicCBYx4JdEACUqZQKBgQDF6n/xEgiCrsKwuFYu+Lx+Yy8OA3xStys+\nbSdoCeOdmD23w8wugEIipj8wdEMCOvPMlfTVr9ZflP0n7zQxoXJNF2TAopz3BOM3\nyugfA7H0K1bsUi9GI/txKf4exHYd4dimvZivH+yJKaE4ZNG6SXuv3kq6g5LhPC3p\nY/TuUiWL5QKBgDFWVxB41MqFrTRTW/c0srJQp998CCISitFriFaeLTDTIby2yKB7\nt5glyr9F/s3oNrOLdGnAM8cftx+mMr1SHFuu8QuhYjkD7H3levfW6WmjbwIcCJjZ\nB/fz3xhDaVZPl1gtSctlSyw4gD609FOOUaNr8h83D53sGKREaUl4G3s9AoGAKh/w\nXWImN5J00+JYTaUZkZkQwd3SD1T3OlFHSuiX7sohkMR26AraiL9zwZ9tR8M+cvQT\n6YuEiFGQ1HggVtPzHR92jV3PJPCAYDaq0zcZIEw9Mw2HDFnKQdrbQLc2IMQaNdsy\n7UtRMByROQyUax8K2XLp2ur4T0Jcz0k8L6GCZlUCgYEAsSTorw02ZEmTE6Dbu44+\n2DQfFYeeydvdIIAnZY2TFoE8ky3zaY4L4RQOufXm+a7Isi9VXkdWZCurJqFCa6+n\ne1N8kCm5akOq0GXV8fpeVYb6ZDcCiUI5vWtjbM6+oBlpjUac6lNkwx6OUA1nBuQ9\nglPpnclBNoUOijdyw1NUCDg=\n-----END PRIVATE KEY-----\n",
    "client_email": "firebase-adminsdk-fbsvc@altoyclaro-tfg.iam.gserviceaccount.com",
    "client_id": "113328895236229106027",
    "token_uri": "https://oauth2.googleapis.com/token"
}

FIREBASE_PROJECT_ID = "altoyclaro-tfg"

# ── FUNCIONES ─────────────────────────────────────────────────────────────────

def obtener_access_token():
    """Genera un OAuth2 access token para FCM API V1."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    now = int(time.time())
    header  = base64.urlsafe_b64encode(json.dumps({"alg":"RS256","typ":"JWT"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps({
        "iss":   FIREBASE_CREDENTIALS["client_email"],
        "sub":   FIREBASE_CREDENTIALS["client_email"],
        "aud":   "https://oauth2.googleapis.com/token",
        "iat":   now,
        "exp":   now + 3600,
        "scope": "https://www.googleapis.com/auth/firebase.messaging"
    }).encode()).rstrip(b"=")

    signing_input = header + b"." + payload
    private_key = serialization.load_pem_private_key(
        FIREBASE_CREDENTIALS["private_key"].encode(), password=None
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")
    jwt_token = (signing_input + b"." + sig_b64).decode()

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
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())["access_token"]


def enviar_push(fcm_token, titulo, cuerpo):
    """Envía una notificación push via FCM API V1."""
    access_token = obtener_access_token()
    payload = json.dumps({
        "message": {
            "token": fcm_token,
            "notification": {"title": titulo, "body": cuerpo},
            "android": {"priority": "high"},
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
            print(f"✅ Push enviado correctamente: {resp.read().decode()}")
            return True
    except urllib.error.HTTPError as e:
        print(f"❌ Error FCM {e.code}: {e.read().decode()}")
        return False


def forzar_ventana(usuario_id):
    """Crea o actualiza la ventana EMA del usuario para ahora mismo."""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cursor = conn.cursor()

    ahora_utc  = datetime.now(pytz.utc)
    cierre_utc = ahora_utc + timedelta(minutes=31)
    hoy        = ahora_utc.date()

    cursor.execute("""
        INSERT INTO ventanas_diarias (usuario_id, fecha, hora_notificacion, hora_cierre, respondida)
        VALUES (%s, %s, %s, %s, FALSE)
        ON CONFLICT (usuario_id, fecha) DO UPDATE
            SET hora_notificacion = EXCLUDED.hora_notificacion,
                hora_cierre       = EXCLUDED.hora_cierre,
                respondida        = FALSE
    """, (usuario_id, hoy, ahora_utc, cierre_utc))

    conn.commit()
    cursor.close()
    conn.close()
    print(f"✅ Ventana creada: abierta hasta las {cierre_utc.strftime('%H:%M')} UTC")


def listar_usuarios():
    """Muestra los usuarios disponibles."""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre_usuario, fcm_token, region FROM usuarios WHERE email_verificado = TRUE")
    usuarios = cursor.fetchall()
    cursor.close()
    conn.close()
    return usuarios


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  FORZAR NOTIFICACIÓN — Alto y Claro (Demo)")
    print("=" * 50)

    usuarios = listar_usuarios()

    if not usuarios:
        print("❌ No hay usuarios verificados en la base de datos.")
        exit()

    print("\nUsuarios disponibles:")
    for u in usuarios:
        token_ok = "✅ token" if u["fcm_token"] else "❌ sin token"
        print(f"  [{u['id']}] {u['nombre_usuario']} — {token_ok}")

    print()
    usuario_id = int(input("Introduce el ID del usuario: "))
    usuario = next((u for u in usuarios if u["id"] == usuario_id), None)

    if not usuario:
        print("❌ Usuario no encontrado.")
        exit()

    print(f"\n→ Forzando ventana para: {usuario['nombre_usuario']}")
    forzar_ventana(usuario_id)

    if usuario["fcm_token"]:
        print("→ Enviando notificación push...")
        enviar_push(
            usuario["fcm_token"],
            "Alto y Claro 🌿",
            "¡Es tu momento! Tienes 30 minutos para registrar cómo estás."
        )
    else:
        print("⚠️  El usuario no tiene token FCM — la ventana está abierta pero no llegará notificación.")
        print("   Abre la app en el emulador para verlo.")

    print("\n¡Listo! Abre la app en el emulador y verás la ventana activa.")