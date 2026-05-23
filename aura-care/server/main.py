"""
Aura-Care · main.py
────────────────────
Punto de entrada único.
Arranca en el mismo event loop asyncio:
  · Servidor UDP de ingesta CSI  (ingest.py)
  · Servidor web FastAPI          (web.py   via uvicorn)
  · Actualizador de PPS           (ingest.py)
"""

import asyncio
import uvicorn

import state as st
from notifications import build_notification_bus
from detector import FallDetector
from ingest import start_udp, pps_updater
from web import app


async def main():
    print("╔══════════════════════════════════════╗")
    print("║       AURA-CARE  —  Iniciando        ║")
    print("╚══════════════════════════════════════╝")

    # Construir bus de notificaciones y detector
    bus      = build_notification_bus()
    detector = FallDetector(notification_bus=bus)

    # Iniciar servidor UDP
    transport = await start_udp(detector)

    # Iniciar servidor web (uvicorn en el mismo loop)
    config = uvicorn.Config(
        app,
        host=st.WEB_HOST,
        port=st.WEB_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    print(f"[Web] Dashboard en http://{st.WEB_HOST}:{st.WEB_PORT}")
    print(f"[Web] API JSON  en http://{st.WEB_HOST}:{st.WEB_PORT}/api/state\n")

    try:
        await asyncio.gather(
            server.serve(),
            pps_updater(),
        )
    finally:
        transport.close()
        print("[Aura-Care] Servidor detenido.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
