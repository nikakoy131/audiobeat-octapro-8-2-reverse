"""Decoder for the 242-byte per-channel block returned by CMD 0x05 READ_BLOCK."""

import struct
from collections.abc import Callable
from dataclasses import dataclass, field

from octapro.protocol.constants import KNOWN_SLOPES
from octapro.protocol.eq import EqBand, parse_eq_block
from octapro.protocol.routing import RoutingMatrix, parse_routing

WarnFn = Callable[[str, object, str], None]

BLOCK_LEN = 242
EQ_BLOCK_OFFSET = 53  # byte 53 of the data payload


@dataclass
class ChannelBlock:
    channel: int
    raw: bytes
    routing: RoutingMatrix
    hpf_freq_hz: float
    hpf_slope_byte: int
    lpf_freq_hz: float
    lpf_slope_byte: int
    eq_bands: list[EqBand]
    # Bytes not yet understood — logged for research
    unknown_bytes: dict[str, str] = field(default_factory=dict)


def parse_channel_block(
    raw: bytes,
    ch: int,
    warn: WarnFn | None = None,
) -> ChannelBlock:
    """
    Parse 242-byte channel data payload (bytes [8:] of an IN packet).

    Block layout (PROTOCOL.md):
      [0]       prefix 0x00
      [1:33]    routing matrix (32 bytes)
      [33:39]   UNKNOWN (6 bytes)
      [39:43]   float32 LE HPF freq (Hz)
      [43]      HPF slope code
      [44]      UNKNOWN byte
      [45:49]   float32 LE LPF freq (Hz)
      [49]      LPF slope code
      [50:52]   UNKNOWN flags (2 bytes)
      [52]      EQ section marker 0x06
      [53:239]  EQ data: 31 bands × 6 bytes
      [239]     trailing byte (varies per channel)
      [240:242] padding zeros
    """
    def _u8(i: int) -> int:
        return raw[i] if i < len(raw) else 0

    def _f32(i: int) -> float:
        return struct.unpack_from("<f", raw, i)[0] if i + 4 <= len(raw) else 0.0

    if len(raw) < BLOCK_LEN and warn:
        warn("short_block", len(raw), f"ch={ch} expected {BLOCK_LEN}")

    prefix = _u8(0)
    if prefix != 0x00 and warn:
        warn("block_prefix", f"0x{prefix:02x}", f"ch={ch} expected 0x00")

    routing = parse_routing(raw, offset=1)

    hpf_freq = _f32(39)
    hpf_slope = _u8(43)
    if hpf_slope not in KNOWN_SLOPES and warn:
        warn("hpf_slope_code", f"0x{hpf_slope:02x}", f"ch={ch}")

    lpf_freq = _f32(45)
    lpf_slope = _u8(49)
    if lpf_slope not in KNOWN_SLOPES and warn:
        warn("lpf_slope_code", f"0x{lpf_slope:02x}", f"ch={ch}")

    eq_marker = _u8(52)
    if eq_marker != 0x06 and warn:
        warn("eq_marker", f"0x{eq_marker:02x}", f"ch={ch} expected 0x06")

    eq_bands = parse_eq_block(raw, offset=EQ_BLOCK_OFFSET, warn=warn)

    unknowns: dict[str, str] = {
        "bytes_33_39": raw[33:39].hex() if len(raw) >= 39 else "",
        "byte_44": f"0x{_u8(44):02x}",
        "flags_50_52": raw[50:52].hex() if len(raw) >= 52 else "",
        "eq_marker": f"0x{eq_marker:02x}",
        "trailing_239": f"0x{_u8(239):02x}",
        "padding_240_242": raw[240:242].hex() if len(raw) >= 242 else "",
    }

    return ChannelBlock(
        channel=ch,
        raw=raw,
        routing=routing,
        hpf_freq_hz=hpf_freq,
        hpf_slope_byte=hpf_slope,
        lpf_freq_hz=lpf_freq,
        lpf_slope_byte=lpf_slope,
        eq_bands=eq_bands,
        unknown_bytes=unknowns,
    )
