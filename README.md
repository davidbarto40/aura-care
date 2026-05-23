# Aura-Care · Sistema de Teleasistencia WiFi-CSI

Sistema comercial de teleasistencia para ancianos que detecta **presencia y caídas sin cámaras**, usando la señal WiFi CSI (Channel State Information) capturada por placas ESP32-S3.

---

## Arquitectura

```
[ESP32-S3 ×5]  ──UDP:5005──►  [main.py]
                                  ├── ingest.py      ← servidor UDP asíncrono
                                  ├── signal_proc.py ← filtro Butterworth + varianza
                                  ├── detector.py    ← máquina de estados (caídas)
                                  ├── notifications.py← Telegram + Webhook
                                  ├── web.py         ← FastAPI + SSE
                                  └── state.py       ← estado compartido en memoria

                          http://servidor:8080  ◄──  [Navegador · Dashboard]
```

---

## Instalación

```bash
git clone https://github.com/tu-usuario/aura-care.git
cd aura-care
pip install -r requirements.txt
```

---

## Configuración

Editar `server/state.py`:

| Variable | Descripción |
|---|---|
| `BOARD_ZONE_MAP` | Dict `{ip: "nombre de zona"}` para cada ESP32-S3 |
| `TELEGRAM_TOKEN` | Token del bot de Telegram |
| `TELEGRAM_CHAT_ID` | Chat ID de destino |
| `WEBHOOK_URL` | Endpoint externo (si `WEBHOOK_ENABLED = True`) |
| `FALL_IMPACT_THR` | Umbral de varianza para considerar impacto (calibrar con datos reales) |
| `FALL_STILL_SECS` | Segundos de inmovilidad para confirmar caída (por defecto 15) |

---

## Arranque

```bash
cd server
python main.py
```

El dashboard estará disponible en `http://localhost:8080`.

---

## Firmware ESP32-S3

Requisito: **ESP-IDF** instalado.

1. Activar CSI en menuconfig:
   ```
   idf.py menuconfig → Component config → Wi-Fi → [*] Enable Wi-Fi CSI
   ```

2. Editar `firmware/main.c`:
   ```c
   #define WIFI_SSID   "TU_RED_WIFI"
   #define WIFI_PASS   "TU_CONTRASEÑA"
   #define SERVER_IP   "192.168.1.X"   // IP del servidor
   ```

3. Compilar y flashear:
   ```bash
   idf.py build
   idf.py -p /dev/ttyUSB0 flash monitor
   ```

---

## Calibración de umbrales

Una vez las placas estén enviando datos:

1. Observar la varianza en reposo → ajustar `VAR_EMPTY_THR`
2. Caminar por la habitación → observar pico → ajustar `VAR_MOTION_THR`
3. Tirar un objeto pesado al suelo → observar pico → ajustar `FALL_IMPACT_THR` al 80% de ese valor

---

## Máquina de estados

```
IDLE
 └─[pico ≥3 placas simultáneo]─► IMPACTO_DETECTADO
                                       │
                                  (inmediato)
                                       │
                               MONITORIZANDO_INMOVILIDAD
                                  /                 \
          [inmóvil >15 s]                    [movimiento / timeout]
                │                                    │
         🚨 ALERTA_CAIDA                      ✅ FALSA_ALARMA
                │                                    │
          (30 s cooldown) ◄────── IDLE ─────► (30 s cooldown)
```

---

## Añadir un canal de notificación

Crear una subclase de `NotificationChannel` en `notifications.py` y registrarla:

```python
class MiCanal(NotificationChannel):
    async def send(self, payload: AlertPayload) -> bool:
        # tu lógica aquí
        return True

# En build_notification_bus():
bus.register(MiCanal(...))
```

---

## Estructura del repositorio

```
aura-care/
├── server/
│   ├── main.py           ← punto de entrada
│   ├── state.py          ← configuración y estado global
│   ├── ingest.py         ← servidor UDP
│   ├── signal_proc.py    ← filtro y varianza
│   ├── detector.py       ← detección de caídas
│   ├── notifications.py  ← Telegram + Webhook
│   └── web.py            ← API y dashboard
├── templates/
│   └── dashboard.html    ← interfaz web
├── firmware/
│   └── main.c            ← firmware ESP32-S3 (ESP-IDF)
└── requirements.txt
```
