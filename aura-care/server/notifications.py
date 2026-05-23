"""
Aura-Care · notifications.py
─────────────────────────────
NotificationBus con canales pluggables.
Para añadir un canal: crear subclase de NotificationChannel
y registrarla en build_notification_bus().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import aiohttp
import asyncio

import state as st


@dataclass
class AlertPayload:
    timestamp:     str
    still_secs:    float
    impact_boards: list[str]
    impact_zones:  list[str]
    variances:     dict


class NotificationChannel(ABC):
    @abstractmethod
    async def send(self, payload: AlertPayload) -> bool: ...


# ── Canal 1: Telegram ─────────────────────────────────────────────────────────
class TelegramChannel(NotificationChannel):
    def __init__(self, token: str, chat_id: str):
        self.url     = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id

    def _build_message(self, p: AlertPayload) -> str:
        zone_lines = "".join(
            f"  • {zone}  ({ip})\n"
            for ip, zone in zip(p.impact_boards, p.impact_zones)
        )
        return (
            "🚨 *AURA-CARE — ALERTA DE CAÍDA* 🚨\n\n"
            f"🕐 *Hora:* {p.timestamp}\n"
            f"⏱ *Inmovilidad confirmada:* {p.still_secs:.0f} s\n\n"
            "📡 *Zonas con mayor impacto:*\n"
            f"{zone_lines}\n"
            "⚠️ Por favor, compruebe el estado del usuario de inmediato."
        )

    async def send(self, payload: AlertPayload) -> bool:
        body = {
            "chat_id":    self.chat_id,
            "text":       self._build_message(payload),
            "parse_mode": "Markdown",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url, json=body,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    ok = resp.status == 200
                    print(
                        f"[Telegram] {'✅ Enviado' if ok else f'❌ Error {resp.status}'}"
                    )
                    return ok
        except Exception as exc:
            print(f"[Telegram] ❌ Excepción: {exc}")
            return False


# ── Canal 2: Webhook HTTP POST ────────────────────────────────────────────────
class WebhookChannel(NotificationChannel):
    def __init__(self, url: str, secret: str):
        self.url    = url
        self.secret = secret

    async def send(self, payload: AlertPayload) -> bool:
        body = {
            "event":         "FALL_DETECTED",
            "timestamp":     payload.timestamp,
            "still_seconds": payload.still_secs,
            "impact_boards": payload.impact_boards,
            "impact_zones":  payload.impact_zones,
            "variances":     payload.variances,
        }
        headers = {
            "Content-Type":  "application/json",
            "X-Aura-Secret": self.secret,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url, json=body, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    ok = 200 <= resp.status < 300
                    print(
                        f"[Webhook] {'✅ Enviado' if ok else f'❌ Error {resp.status}'}"
                    )
                    return ok
        except Exception as exc:
            print(f"[Webhook] ❌ Excepción: {exc}")
            return False


# ── Bus central ───────────────────────────────────────────────────────────────
class NotificationBus:
    def __init__(self):
        self._channels: list[NotificationChannel] = []

    def register(self, ch: NotificationChannel):
        self._channels.append(ch)
        print(f"[NotifBus] Registrado: {ch.__class__.__name__}")

    async def dispatch(self, payload: AlertPayload):
        if not self._channels:
            return
        results = await asyncio.gather(
            *(ch.send(payload) for ch in self._channels),
            return_exceptions=True,
        )
        failed = sum(1 for r in results if r is not True)
        if failed:
            print(f"[NotifBus] ⚠️ {failed}/{len(results)} canales fallaron")


def build_notification_bus() -> NotificationBus:
    """Punto único de configuración de canales."""
    bus = NotificationBus()
    if st.TELEGRAM_ENABLED:
        bus.register(TelegramChannel(st.TELEGRAM_TOKEN, st.TELEGRAM_CHAT_ID))
    if st.WEBHOOK_ENABLED:
        bus.register(WebhookChannel(st.WEBHOOK_URL, st.WEBHOOK_SECRET))
    return bus
