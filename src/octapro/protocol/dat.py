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

# Per-block layout offsets (relative to block start, derived from dsp_m2.dat and
# verified 2026-07-06 against an app export with known CH1 values gain=-10.0,
# delay=2.5 ms, speaker type=HF):
#  [0:30]    routing matrix (30 bytes; device read-format — NOT the CMD 0x20
#            write format; earlier notes over-read this as 32 bytes)
#  [30:34]   float32 LE per-channel GAIN (dB)
#  [34:38]   float32 LE per-channel DELAY (ms)
#  [38:42]   float32 LE HPF freq (Hz)
#  [42]      HPF slope code (dB/oct = (code+1)*6; 0x00=6 … 0x05=36 … 0x07=48)
#  [43]      HPF filter type (0=Linkwitz-Riley, 1=Bessel, 2=Butterworth)
#  [44:48]   float32 LE LPF freq (Hz); 20600.0 = bypass
#  [48]      LPF slope code
#  [49]      LPF filter type
#  [50]      UNKNOWN byte (observed 0x00)
#  [51]      SPEAKER TYPE (1..6 = HF/MF/LF/MHF/MLF/FF, menu order)
#  [52:238]  EQ data: 31 bands × 6 bytes (exactly fills the block)
GAIN_OFFSET = 30
DELAY_OFFSET = 34
HPF_FREQ_OFFSET = 38
HPF_SLOPE_OFFSET = 42
HPF_TYPE_OFFSET = 43
LPF_FREQ_OFFSET = 44
LPF_SLOPE_OFFSET = 48
LPF_TYPE_OFFSET = 49
SPEAKER_TYPE_OFFSET = 51
EQ_OFFSET = 52


@dataclass
class DatChannel:
    index: int  # 1-based
    raw: bytes
    routing: RoutingMatrix
    gain_db: float
    delay_ms: float
    hpf_freq_hz: float
    hpf_slope_byte: int
    hpf_type_byte: int
    lpf_freq_hz: float
    lpf_slope_byte: int
    lpf_type_byte: int
    speaker_type_byte: int
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

    gain_db = _f32(GAIN_OFFSET)
    delay_ms = _f32(DELAY_OFFSET)
    hpf_freq = _f32(HPF_FREQ_OFFSET)
    hpf_slope = _u8(HPF_SLOPE_OFFSET)
    if hpf_slope not in KNOWN_SLOPES and warn:
        warn("dat_hpf_slope", f"0x{hpf_slope:02x}", f"ch={ch_index}")
    hpf_type = _u8(HPF_TYPE_OFFSET)
    lpf_freq = _f32(LPF_FREQ_OFFSET)
    lpf_slope = _u8(LPF_SLOPE_OFFSET)
    if lpf_slope not in KNOWN_SLOPES and warn:
        warn("dat_lpf_slope", f"0x{lpf_slope:02x}", f"ch={ch_index}")
    lpf_type = _u8(LPF_TYPE_OFFSET)
    speaker_type = _u8(SPEAKER_TYPE_OFFSET)
    # EQ fills [52:238] exactly (31 × 6 = 186 bytes)
    eq_bands = parse_eq_block(block, offset=EQ_OFFSET, warn=warn)

    return DatChannel(
        index=ch_index,
        raw=block,
        routing=routing,
        gain_db=gain_db,
        delay_ms=delay_ms,
        hpf_freq_hz=hpf_freq,
        hpf_slope_byte=hpf_slope,
        hpf_type_byte=hpf_type,
        lpf_freq_hz=lpf_freq,
        lpf_slope_byte=lpf_slope,
        lpf_type_byte=lpf_type,
        speaker_type_byte=speaker_type,
        eq_bands=eq_bands,
        unknown_bytes={
            "byte_50": f"0x{_u8(50):02x}",
        },
    )
