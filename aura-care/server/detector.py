"""
Aura-Care · detector.py
────────────────────────
Máquina de estados para detección de caídas.
Lee varianzas de state.boards y actualiza state.fall_state.

Transiciones:
  IDLE
    → IMPACT_DETECTED   si ≥ FALL_BOARDS_REQUIRED placas superan
                        FALL_IMPACT_THR en ventana FALL_IMPACT_WINDOW s
  IMPACT_DETECTED
    → MONITORING_STILL  inmediato
  MONITORING_STILL
    → ALERTA_CAIDA      si TODAS las placas < FALL_STILL_THR
                        durante FALL_STILL_SECS segundos
    → FALSE_ALARM       si cualquier placa > FALL_RECOVERY_THR
    → FALSE_ALARM       timeout > FALL_MONITOR_WINDOW
  ALERTA_CAIDA / FALSE_ALARM
    → IDLE              tras FALL_RESET_COOLDOWN s
"""

import enum
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import state as st
from notifications import NotificationBus, AlertPayload


class FallState(enum.Enum):
    IDLE             = "IDLE"
    IMPACT_DETECTED  = "IMPACTO_DETECTADO"
    MONITORING_STILL = "MONITORIZANDO_INMOVILIDAD"
    ALERTA_CAIDA     = "🚨 ALERTA_CAIDA"
    FALSE_ALARM      = "✅ FALSA_ALARMA"


_STATE_COLORS = {
    FallState.IDLE:             "#30363d",
    FallState.IMPACT_DETECTED:  "#ffd43b",
    FallState.MONITORING_STILL: "#ff922b",
    FallState.ALERTA_CAIDA:     "#fa5252",
    FallState.FALSE_ALARM:      "#51cf66",
}


@dataclass
class FallDetector:
    notification_bus: Optional[NotificationBus] = None

    _state:          FallState = field(default=FallState.IDLE,  init=False)
    _impact_times:   dict      = field(default_factory=dict,    init=False)
    _monitor_start:  float     = field(default=0.0,             init=False)
    _still_since:    float     = field(default=0.0,             init=False)
    _resolved_at:    float     = field(default=0.0,             init=False)
    _pending_alert:  Optional[AlertPayload] = field(default=None, init=False)

    def _set(self, new: FallState):
        self._state    = new
        st.fall_state  = new.value
        st.fall_color  = _STATE_COLORS[new]

    def _log(self, msg: str):
        ts    = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        print(f"\n{'═'*64}\n  AURA-CARE  {entry}\n{'═'*64}\n")

    def update(self, variances: dict[str, float]):
        now = time.monotonic()

        # ── Cooldown post-resolución ──────────────────────────────────────────
        if self._state in (FallState.ALERTA_CAIDA, FallState.FALSE_ALARM):
            if now - self._resolved_at >= st.FALL_RESET_COOLDOWN:
                self._set(FallState.IDLE)
                self._impact_times.clear()
            return

        # ── IDLE: buscar pico simultáneo ──────────────────────────────────────
        if self._state == FallState.IDLE:
            for ip, var in variances.items():
                if var >= st.FALL_IMPACT_THR:
                    self._impact_times[ip] = now

            self._impact_times = {
                ip: t for ip, t in self._impact_times.items()
                if now - t <= st.FALL_IMPACT_WINDOW
            }

            if len(self._impact_times) >= st.FALL_BOARDS_REQUIRED:
                self._log(
                    f"IMPACTO en {len(self._impact_times)} placas: "
                    f"{list(self._impact_times.keys())}"
                )
                self._set(FallState.IMPACT_DETECTED)
                self._monitor_start = now
                self._still_since   = now

        # ── IMPACT_DETECTED → MONITORING ─────────────────────────────────────
        if self._state == FallState.IMPACT_DETECTED:
            self._set(FallState.MONITORING_STILL)

        # ── MONITORING_STILL ─────────────────────────────────────────────────
        if self._state == FallState.MONITORING_STILL:
            elapsed = now - self._monitor_start

            if elapsed > st.FALL_MONITOR_WINDOW:
                self._log("FALSA ALARMA — timeout")
                self._resolved_at = now
                self._set(FallState.FALSE_ALARM)
                self._record_alert(variances, confirmed=False)
                return

            if any(v > st.FALL_RECOVERY_THR for v in variances.values()):
                self._log("FALSA ALARMA — movimiento post-impacto (se levantó)")
                self._resolved_at = now
                self._set(FallState.FALSE_ALARM)
                self._record_alert(variances, confirmed=False)
                return

            if all(v < st.FALL_STILL_THR for v in variances.values()):
                still_dur = now - self._still_since
                if still_dur >= st.FALL_STILL_SECS:
                    self._log(
                        f"🚨 ALERTA CONFIRMADA — inmovilidad {still_dur:.1f} s"
                    )
                    self._resolved_at = now
                    self._set(FallState.ALERTA_CAIDA)
                    self._record_alert(variances, confirmed=True, still_secs=still_dur)
            else:
                self._still_since = now

    def _record_alert(self, variances: dict, confirmed: bool, still_secs: float = 0.0):
        top_boards = sorted(
            self._impact_times.keys(),
            key=lambda ip: variances.get(ip, 0.0),
            reverse=True,
        )
        top_zones = [
            st.BOARD_ZONE_MAP.get(ip, f"Zona-{ip.split('.')[-1]}")
            for ip in top_boards
        ]
        record = st.AlertRecord(
            timestamp     = datetime.now().isoformat(timespec="seconds"),
            still_secs    = still_secs,
            impact_boards = top_boards,
            impact_zones  = top_zones,
            variances     = dict(variances),
            resolved      = not confirmed,
        )
        st.add_alert(record)

        if confirmed:
            self._pending_alert = AlertPayload(
                timestamp     = record.timestamp,
                still_secs    = still_secs,
                impact_boards = top_boards,
                impact_zones  = top_zones,
                variances     = dict(variances),
            )

    async def dispatch_pending(self):
        if self._pending_alert and self.notification_bus:
            payload = self._pending_alert
            self._pending_alert = None
            await self.notification_bus.dispatch(payload)
