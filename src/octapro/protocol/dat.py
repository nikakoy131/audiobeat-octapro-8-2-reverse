"""Parser for US002 .dat preset files (header + 10 × 238-byte channel blocks)."""

import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from octapro.errors import ParseError
from octapro.protocol.eq import EqBand, parse_eq_block
from octapro.protocol.routing import RoutingMatrix, parse_routing

WarnFn = Callable[[str, object, str], None]

HEADER_MAGIC = b"US002"
BLOCK_LEN = 238
MIN_FILE_LEN = len(HEADER_MAGIC) + 10 * BLOCK_LEN  # 2385

# Per-block layout offsets (relative to block start, derived from dsp_m2.dat):
#  [0:32]    routing matrix (32 bytes; signed int8 /10.0, 0x80 = mute)
#  [32:38]   UNKNOWN (6 bytes) — decode to non-filter floats; meaning TBD
#  [38:42]   float32 LE HPF freq (Hz)
#  [42]      HPF slope code (0x05=36 dB/oct, 0x03=12 dB/oct)
#  [43]      UNKNOWN byte (observed 0x00)
#  [44:48]   float32 LE LPF freq (Hz); 20600.0 = bypass
#  [48]      LPF slope code
#  [49:52]   UNKNOWN (3 bytes) — byte [51] varies; meaning TBD
#  [52:238]  EQ data: 31 bands × 6 bytes (exactly fills the block)


@dataclass
class DatChannel:
    index: int  # 1-based
    raw: bytes
    routing: RoutingMatrix
    hpf_freq_hz: float
    hpf_slope_byte: int
    lpf_freq_hz: float
    lpf_slope_byte: int
    eq_bands: list[EqBand]
    unknown_bytes: dict[str, str] = field(default_factory=dict)


@dataclass
class DatPreset:
    path: Path
    raw: bytes
    channels: list[DatChannel]


def parse_dat(path: Path, warn: WarnFn | None = None) -> DatPreset:
    data = path.read_bytes()
    if not data.startswith(HEADER_MAGIC):
        raise ParseError(f"invalid header magic — expected {HEADER_MAGIC!r}, got {data[:5]!r}")
    if len(data) < MIN_FILE_LEN:
        raise ParseError(f"file too short: {len(data)} bytes, need at least {MIN_FILE_LEN}")

    channels = []
    for i in range(10):
        off = len(HEADER_MAGIC) + i * BLOCK_LEN
        block = data[off : off + BLOCK_LEN]
        channels.append(_parse_block(block, ch_index=i + 1, warn=warn))

    return DatPreset(path=path, raw=data, channels=channels)


def _parse_block(block: bytes, ch_index: int, warn: WarnFn | None) -> DatChannel:
    def _u8(i: int) -> int:
        return block[i] if i < len(block) else 0

    def _f32(i: int) -> float:
        return struct.unpack_from("<f", block, i)[0] if i + 4 <= len(block) else 0.0

    routing = parse_routing(block, offset=0)

    from octapro.protocol.constants import KNOWN_SLOPES

    hpf_freq = _f32(38)
    hpf_slope = _u8(42)
    if hpf_slope not in KNOWN_SLOPES and warn:
        warn("dat_hpf_slope", f"0x{hpf_slope:02x}", f"ch={ch_index}")
    lpf_freq = _f32(44)
    lpf_slope = _u8(48)
    if lpf_slope not in KNOWN_SLOPES and warn:
        warn("dat_lpf_slope", f"0x{lpf_slope:02x}", f"ch={ch_index}")
    # EQ fills [52:238] exactly (31 × 6 = 186 bytes)
    eq_bands = parse_eq_block(block, offset=52, warn=warn)

    return DatChannel(
        index=ch_index,
        raw=block,
        routing=routing,
        hpf_freq_hz=hpf_freq,
        hpf_slope_byte=hpf_slope,
        lpf_freq_hz=lpf_freq,
        lpf_slope_byte=lpf_slope,
        eq_bands=eq_bands,
        unknown_bytes={
            "bytes_32_38": block[32:38].hex() if len(block) >= 38 else "",
            "byte_43": f"0x{_u8(43):02x}",
            "bytes_49_52": block[49:52].hex() if len(block) >= 52 else "",
        },
    )
