"""Parser for the 31-band EQ block (31 × 6 bytes)."""

import struct
from collections.abc import Callable
from dataclasses import dataclass

from octapro.protocol.constants import (
    EQ_BAND_COUNT,
    EQ_BAND_STRIDE,
    EQ_Q_MAX_BYTE,
    EQ_Q_MIN_BYTE,
)
from octapro.protocol.gain import eq_byte_to_db

WarnFn = Callable[[str, object, str], None]

_Q_SCALE = 10.0


def q_to_byte(q: float) -> int:
    """Encode a Q factor to its byte. q_byte = round(Q * 10); default 0x0a = Q 1.0.

    Live-verified 2026-07-06 (Q 2.9 -> 0x1d). Clamps to [0, 255].
    """
    return max(0, min(0xFF, round(q * _Q_SCALE)))


def byte_to_q(b: int) -> float:
    """Decode a Q byte to its factor (Q = byte / 10)."""
    return b / _Q_SCALE


@dataclass
class EqBand:
    index: int          # 0-based
    freq_hz: float
    gain_db: float
    gain_byte: int
    q_byte: int

    @property
    def q(self) -> float:
        """Q factor (q_byte / 10; live-verified 2026-07-06)."""
        return byte_to_q(self.q_byte)


def parse_eq_block(
    data: bytes,
    offset: int = 0,
    warn: WarnFn | None = None,
) -> list[EqBand]:
    """Parse EQ_BAND_COUNT × EQ_BAND_STRIDE bytes starting at `offset`."""
    bands: list[EqBand] = []
    for i in range(EQ_BAND_COUNT):
        pos = offset + i * EQ_BAND_STRIDE
        if pos + EQ_BAND_STRIDE > len(data):
            break
        freq_hz = struct.unpack_from("<f", data, pos)[0]
        gain_byte = data[pos + 4]
        q_byte = data[pos + 5]
        # Q = q_byte / 10 is live-verified, so a non-default Q is just a user
        # setting; only flag values the device can't legitimately produce.
        if not (EQ_Q_MIN_BYTE <= q_byte <= EQ_Q_MAX_BYTE) and warn:
            warn(
                "eq_q_byte",
                f"0x{q_byte:02x}",
                f"band {i} freq={freq_hz:.1f} Hz "
                f"(outside 0x{EQ_Q_MIN_BYTE:02x}..0x{EQ_Q_MAX_BYTE:02x})",
            )
        bands.append(EqBand(
            index=i,
            freq_hz=freq_hz,
            gain_db=eq_byte_to_db(gain_byte),
            gain_byte=gain_byte,
            q_byte=q_byte,
        ))
    return bands
