"""Gain byte encoding used throughout the protocol.

gain_dB = (byte - 0x78) / 10.0
0x80     = mute / -inf
0x78     = 0.0 dB
0xdc     = +10.0 dB
0x6e     = -1.0 dB
"""

from octapro.protocol.constants import GAIN_MUTE_BYTE, GAIN_ZERO_BYTE

_SCALE = 10.0


def byte_to_db(b: int) -> float | None:
    """Return dB value, or None if the byte encodes mute."""
    if b == GAIN_MUTE_BYTE:
        return None
    return (b - GAIN_ZERO_BYTE) / _SCALE


def db_to_byte(db: float) -> int:
    """Encode dB to gain byte. Clamps to [0, 255]."""
    return max(0, min(0xFF, round(db * _SCALE) + GAIN_ZERO_BYTE))


def format_gain(b: int) -> str:
    val = byte_to_db(b)
    return "MUTE" if val is None else f"{val:+.1f} dB"
