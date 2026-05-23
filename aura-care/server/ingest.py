"""
Aura-Care · ingest.py
──────────────────────
Servidor UDP asíncrono. Recibe paquetes CSI de los ESP32-S3,
los parsea y actualiza el estado global en state.py.
"""

import asyncio
import time

import state as st
from signal_proc import parse_csi_amplitudes, process_sample
from detector import FallDetector


class CSIProtocol(asyncio.DatagramProtocol):
    def __init__(self, detector: FallDetector):
        self.detector = detector

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple):
        ip  = addr[0]
        now = time.monotonic()

        # Registrar placa nueva
        if ip not in st.boards:
            if len(st.boards) >= st.MAX_BOARDS:
                return
            board = st.register_board(ip)
            print(f"[Ingest] Nueva placa: {ip} → {board.zone}  "
                  f"({len(st.boards)}/{st.MAX_BOARDS})")
        else:
            board = st.boards[ip]

        # PPS
        board.pps_window.append(now)

        # Procesar señal CSI
        amplitudes = parse_csi_amplitudes(data)
        if amplitudes is not None:
            process_sample(board, amplitudes)

            # Actualizar detector con snapshot de varianzas actual
            variances = {ip: b.variance for ip, b in st.boards.items()}
            self.detector.update(variances)

            # Despachar alertas pendientes sin bloquear
            if self.detector._pending_alert:
                loop = asyncio.get_event_loop()
                loop.create_task(self.detector.dispatch_pending())

    def error_received(self, exc):
        print(f"[Ingest] Error UDP: {exc}")

    def connection_lost(self, exc):
        pass


async def pps_updater():
    """Actualiza el campo pps de cada placa cada 2 segundos."""
    while True:
        await asyncio.sleep(st.STATS_INTERVAL)
        now    = time.monotonic()
        cutoff = now - st.STATS_INTERVAL
        for board in st.boards.values():
            board.pps_window = [t for t in board.pps_window if t >= cutoff]
            board.pps = len(board.pps_window) / st.STATS_INTERVAL

        # Log de consola
        lines = [f"[{board.ip:<16}] {board.pps:5.1f} pps  "
                 f"var={board.variance:8.4f}  {board.status_label().upper()}"
                 for board in st.boards.values()]
        if lines:
            print(f"\n── Estado  fall={st.fall_state} ──")
            for l in lines:
                print(f"   {l}")


async def start_udp(detector: FallDetector):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: CSIProtocol(detector),
        local_addr=(st.UDP_HOST, st.UDP_PORT),
        allow_broadcast=False,
    )
    print(f"[Ingest] UDP escuchando en {st.UDP_HOST}:{st.UDP_PORT}")
    return transport
