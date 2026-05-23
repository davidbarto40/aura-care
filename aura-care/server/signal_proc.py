"""
Aura-Care · signal.py
──────────────────────
Filtro Butterworth paso-bajo + cálculo de varianza por ventana.
Opera sobre los objetos BoardState de state.py.
"""

import struct
import time

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

from state import (
    BoardState,
    SAMPLE_RATE, CUTOFF_HZ, BUTTER_ORDER, VAR_WINDOW_SEC,
)

# Coeficientes compartidos (iguales para todas las placas)
_SOS = butter(BUTTER_ORDER, CUTOFF_HZ / (SAMPLE_RATE / 2), btype="low", output="sos")


def init_filter(board: BoardState, first_value: float):
    """Inicializa el estado interno del filtro con el primer sample."""
    zi_base = sosfilt_zi(_SOS)
    board.filter_zi = zi_base * first_value


def parse_csi_amplitudes(data: bytes) -> np.ndarray | None:
    """
    Extrae amplitudes de subportadoras del datagrama UDP.

    Formato ESP-IDF (little-endian):
      [uint32 magic 0xABCD1234]  ← opcional
      [uint16 num_subcarriers]
      [int16 real, int16 imag] × num_subcarriers
    """
    try:
        if len(data) < 6:
            return None
        offset = 0
        if len(data) >= 4 and struct.unpack_from("<I", data, 0)[0] == 0xABCD1234:
            offset = 4
        num_sc = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        if len(data) < offset + num_sc * 4 or num_sc == 0:
            return None
        iq = np.frombuffer(data[offset:offset + num_sc * 4], dtype="<i2")
        iq = iq.astype(np.float32).reshape(-1, 2)
        return np.sqrt(iq[:, 0] ** 2 + iq[:, 1] ** 2)
    except Exception:
        return None


def process_sample(board: BoardState, amplitudes: np.ndarray) -> float:
    """
    Aplica filtro Butterworth a la amplitud media,
    acumula en ventana deslizante y devuelve la varianza actual.
    """
    amp_mean = float(np.mean(amplitudes))

    if board.filter_zi is None:
        init_filter(board, amp_mean)

    filtered, board.filter_zi = sosfilt(_SOS, [amp_mean], zi=board.filter_zi)
    filtered_val = float(filtered[0])

    now = time.monotonic()
    board.buf.append((now, filtered_val))

    cutoff      = now - VAR_WINDOW_SEC
    window_vals = [v for t, v in board.buf if t >= cutoff]
    variance    = float(np.var(window_vals)) if len(window_vals) > 1 else 0.0

    board.variance = variance
    board.var_history.append(variance)
    board.last_seen = now

    return variance
