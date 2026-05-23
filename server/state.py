"""
Aura-Care · state.py
────────────────────
Fuente de verdad compartida entre el servidor UDP (ingest.py),
el detector de caídas (detector.py) y la API web (web.py).
Todo es accesible en memoria dentro del mismo proceso asyncio.
"""

import collections
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

# Carga el archivo .env si existe (en producción las variables
# pueden venir del entorno del sistema directamente)
load_dotenv()

# ── Configuración global ──────────────────────────────────────────────────────
UDP_HOST        = "0.0.0.0"
UDP_PORT        = 5005
WEB_HOST        = "0.0.0.0"
WEB_PORT        = 8080

MAX_BOARDS      = 5
BUFFER_SIZE     = 512          # paquetes en búfer circular por placa
STATS_INTERVAL  = 2.0          # segundos entre resúmenes de consola

# Señal
SAMPLE_RATE     = 50           # Hz estimados ESP32-S3
CUTOFF_HZ       = 5.0          # frecuencia de corte Butterworth
BUTTER_ORDER    = 4
VAR_WINDOW_SEC  = 1.0
VAR_HISTORY     = 60           # puntos visibles en gráfico

# Umbrales generales
VAR_EMPTY_THR   = 0.02
VAR_MOTION_THR  = 1.5

# Umbrales de caída
FALL_IMPACT_THR      = 8.0
FALL_BOARDS_REQUIRED = 3
FALL_STILL_THR       = 0.05
FALL_STILL_SECS      = 15.0
FALL_RECOVERY_THR    = 0.4
FALL_IMPACT_WINDOW   = 1.5
FALL_MONITOR_WINDOW  = 20.0
FALL_RESET_COOLDOWN  = 30.0

# Mapa IP → nombre de zona (editar tras instalar las placas)
BOARD_ZONE_MAP: dict[str, str] = {
    # "192.168.1.101": "Salón",
    # "192.168.1.102": "Dormitorio",
    # "192.168.1.103": "Baño",
    # "192.168.1.104": "Cocina",
    # "192.168.1.105": "Pasillo",
}

# Telegram  (valores reales en .env, nunca en este fichero)
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = TELEGRAM_TOKEN != ""

# Webhook HTTP (activar cuando haya backend externo)
WEBHOOK_URL     = os.getenv("WEBHOOK_URL",    "https://your-backend.example.com/api/fall-alert")
WEBHOOK_ENABLED = os.getenv("WEBHOOK_ENABLED", "false").lower() == "true"
WEBHOOK_SECRET  = os.getenv("WEBHOOK_SECRET",  "changeme")

# ── Estructuras de datos en memoria ──────────────────────────────────────────

@dataclass
class BoardState:
    ip:          str
    zone:        str
    last_seen:   float = field(default_factory=time.monotonic)
    pps:         float = 0.0
    variance:    float = 0.0
    var_history: collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=VAR_HISTORY)
    )
    buf:         collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=BUFFER_SIZE)
    )
    pps_window:  list  = field(default_factory=list)
    # Estado del filtro (gestionado por signal.py)
    filter_zi:   object = None

    def status_label(self) -> str:
        if self.variance < VAR_EMPTY_THR:
            return "empty"
        if self.variance > VAR_MOTION_THR:
            return "motion"
        return "activity"

    def to_dict(self) -> dict:
        return {
            "ip":          self.ip,
            "zone":        self.zone,
            "pps":         round(self.pps, 1),
            "variance":    round(self.variance, 4),
            "status":      self.status_label(),
            "var_history": list(self.var_history),
            "last_seen":   self.last_seen,
        }


@dataclass
class AlertRecord:
    timestamp:     str
    still_secs:    float
    impact_boards: list[str]
    impact_zones:  list[str]
    variances:     dict
    resolved:      bool = False

    def to_dict(self) -> dict:
        return {
            "timestamp":     self.timestamp,
            "still_secs":    round(self.still_secs, 1),
            "impact_boards": self.impact_boards,
            "impact_zones":  self.impact_zones,
            "variances":     {k: round(v, 4) for k, v in self.variances.items()},
            "resolved":      self.resolved,
        }


# ── Estado global (singleton de módulo) ──────────────────────────────────────
boards:        dict[str, BoardState] = {}   # {ip: BoardState}
board_order:   list[str]             = []   # orden de registro

alert_history: list[AlertRecord]     = []   # todas las alertas de la sesión
fall_state:    str                   = "IDLE"
fall_color:    str                   = "#30363d"


def get_board(ip: str) -> Optional[BoardState]:
    return boards.get(ip)


def register_board(ip: str) -> BoardState:
    zone = BOARD_ZONE_MAP.get(ip, f"Zona-{ip.split('.')[-1]}")
    board = BoardState(ip=ip, zone=zone)
    boards[ip] = board
    board_order.append(ip)
    return board


def add_alert(record: AlertRecord):
    alert_history.append(record)
    # Mantener solo las últimas 100 alertas en memoria
    if len(alert_history) > 100:
        alert_history.pop(0)


def system_snapshot() -> dict:
    """JSON completo del sistema para el dashboard."""
    return {
        "fall_state": fall_state,
        "fall_color": fall_color,
        "boards":     [boards[ip].to_dict() for ip in board_order],
        "alerts":     [a.to_dict() for a in reversed(alert_history)],
        "thresholds": {
            "empty":  VAR_EMPTY_THR,
            "motion": VAR_MOTION_THR,
            "impact": FALL_IMPACT_THR,
        },
    }
