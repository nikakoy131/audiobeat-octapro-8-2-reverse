"""Parser for the 31-band EQ block (31 × 6 bytes)."""

import struct
from collections.abc import Callable
from dataclasses import dataclass

from octapro.protocol.constants import EQ_BAND_COUNT, EQ_BAND_STRIDE, EQ_DEFAULT_Q_BYTE
from octapro.protocol.gain import byte_to_db

WarnFn = Callable[[str, object, str], None]


@dataclass
class EqBand:
    index: int          # 0-based
    freq_hz: float
    gain_db: float | None
    gain_byte: int
    q_byte: int


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
        if q_byte != EQ_DEFAULT_Q_BYTE and warn:
            warn(
                "eq_q_byte",
                f"0x{q_byte:02x}",
                f"band {i} freq={freq_hz:.1f} Hz (expected 0x{EQ_DEFAULT_Q_BYTE:02x})",
            )
        bands.append(EqBand(
            index=i,
            freq_hz=freq_hz,
            gain_db=byte_to_db(gain_byte),
            gain_byte=gain_byte,
            q_byte=q_byte,
        ))
    return bands
