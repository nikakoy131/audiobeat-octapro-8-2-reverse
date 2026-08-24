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
MUTE_FLAG_OFFSET = 29  # 0 = unmuted, 1 = muted (docs/findings/BLE.md "Per-channel mute")

MASTER_BLOCK_LEN = 137
MASTER_PRESET_SLOT_OFFSET = 7  # u8, active preset slot 1..6 (M1..M6) — see below
MASTER_VOLUME_OFFSET = 9    # float32 LE, same value the keepalive echoes
MASTER_NOISE_GATE_OFFSET = 27  # float32 LE, factory noise gate threshold (manual p.9: −88)
MASTER_FW_LEN_OFFSET = 94   # length-prefixed ASCII firmware banner follows

PRESET_SLOT_RANGE = range(1, 7)  # M1..M6


@dataclass
class MasterBlock:
    raw: bytes
    preset_slot: int
    volume_db: float
    noise_gate_db: float
    firmware: str


def parse_master_block(raw: bytes, warn: WarnFn | None = None) -> MasterBlock:
    """Parse the 137-byte master (CH0) data payload.

    Known layout (live dump 2026-07-04, cross-checked against usb1.pcapng frame 162 —
    the two differ only in the volume float and the [134] trailer byte):
      [0:7]     prefix 00 55 55 55 55 55 00
      [7]       u8 **active preset slot (1..6 = M1..M6)** — live-verified
                2026-08-24: RC switched M2 -> M1 with no other device command sent,
                byte-diffed two `read master` captures, only [7] (0x02 -> 0x01) and
                the [134] trailer changed. Previously miscatalogued as part of a
                static "prefix" because every prior sample happened to be taken on
                M2. This is a *live snapshot* of whatever slot the RC last recalled —
                it is NOT retroactive for slots saved/recalled before this device
                was last power-cycled or before any read, and it does not indicate
                whether the live state has since been hand-edited away from that
                slot's saved content (recall pins state at the moment of recall, not
                continuously).
      [8]       0x01 in every sample so far — unconfirmed constant
      [9:13]    float32 LE main volume dB — THE master volume register; the software
                "Main" fader (+6…−60 dB, manual p.10) and the remote-knob volume
                (0–35 steps, manual p.14 "the rotate button adjusts the main volume")
                are two controls for this one value
      [13:27]   unknown (zeros in both dumps)
      [27:31]   float32 LE noise gate threshold dB — factory-set, −88.0 in both dumps;
                matches the "Noise gate threshold" dialog on manual p.9
      [31:94]   unknown — contains two 01 00 02 00 04 00 ... 80 00 bit patterns
      [94]      firmware string length (0x27 = 39)
      [95:95+n] ASCII firmware banner
      [134:137] trailer ([134] varies between reads — checksum-like; tracks [7]:
                the M2->M1 diff moved [134] from 0xe6 to 0xe5, consistent with a
                simple additive checksum that includes byte [7])
    """
    if len(raw) < MASTER_BLOCK_LEN and warn:
        warn("short_master_block", len(raw), f"expected {MASTER_BLOCK_LEN}")

    preset_slot: int = raw[MASTER_PRESET_SLOT_OFFSET] if len(raw) > MASTER_PRESET_SLOT_OFFSET else 0
    if preset_slot not in PRESET_SLOT_RANGE and warn:
        warn(
            "master_preset_slot",
            f"0x{preset_slot:02x}",
            f"expected 1..6 (M1..M6) at offset {MASTER_PRESET_SLOT_OFFSET}",
        )
    volume_db: float = (
        struct.unpack_from("<f", raw, MASTER_VOLUME_OFFSET)[0]
        if len(raw) >= MASTER_VOLUME_OFFSET + 4 else 0.0
    )
    noise_gate_db: float = (
        struct.unpack_from("<f", raw, MASTER_NOISE_GATE_OFFSET)[0]
        if len(raw) >= MASTER_NOISE_GATE_OFFSET + 4 else 0.0
    )
    firmware = ""
    if len(raw) > MASTER_FW_LEN_OFFSET:
        n = raw[MASTER_FW_LEN_OFFSET]
        chunk = raw[MASTER_FW_LEN_OFFSET + 1 : MASTER_FW_LEN_OFFSET + 1 + n]
        firmware = chunk.decode("ascii", errors="replace")
        if not firmware.isprintable() and warn:
            warn("master_fw_banner", chunk.hex(), "non-printable firmware banner")
    return MasterBlock(
        raw=raw,
        preset_slot=preset_slot,
        volume_db=volume_db,
        noise_gate_db=noise_gate_db,
        firmware=firmware,
    )


@dataclass
class ChannelBlock:
    channel: int
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
    muted: bool
    # Bytes not yet understood — logged for research
    unknown_bytes: dict[str, str] = field(default_factory=dict)


def parse_channel_block(
    raw: bytes,
    ch: int,
    warn: WarnFn | None = None,
) -> ChannelBlock:
    """
    Parse 242-byte channel data payload (bytes [8:] of an IN packet).

    Block layout (= .dat block shifted +1; hidden fields decoded & verified
    2026-07-06 against an app export with known CH1 gain/delay/speaker type):
      [0]       prefix 0x00
      [1:31]    routing matrix (30 bytes, device read-format); byte 29 within
                this range doubles as the MUTE flag (0=unmuted, 1=muted) —
                live-verified over BLE on CH1/CH3/CH4/CH6, docs/findings/BLE.md
                "Per-channel mute". Byte 239 is a trailing block checksum that
                tracks it but is not decoded here.
      [31:35]   float32 LE per-channel GAIN (dB)
      [35:39]   float32 LE per-channel DELAY (ms)
      [39:43]   float32 LE HPF freq (Hz)
      [43]      HPF slope code
      [44]      HPF filter type (0=LR, 1=Bessel, 2=Butterworth)
      [45:49]   float32 LE LPF freq (Hz)
      [49]      LPF slope code
      [50]      LPF filter type
      [51]      UNKNOWN byte (observed 0x00)
      [52]      SPEAKER TYPE (1..6) — earlier mislabelled an "EQ marker 0x06"
                because every prior sample happened to be 0x06 (FF)
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

    gain_db = _f32(31)
    delay_ms = _f32(35)
    hpf_freq = _f32(39)
    hpf_slope = _u8(43)
    if hpf_slope not in KNOWN_SLOPES and warn:
        warn("hpf_slope_code", f"0x{hpf_slope:02x}", f"ch={ch}")
    hpf_type = _u8(44)

    lpf_freq = _f32(45)
    lpf_slope = _u8(49)
    if lpf_slope not in KNOWN_SLOPES and warn:
        warn("lpf_slope_code", f"0x{lpf_slope:02x}", f"ch={ch}")
    lpf_type = _u8(50)

    speaker_type = _u8(52)

    muted = _u8(MUTE_FLAG_OFFSET) == 1

    eq_bands = parse_eq_block(raw, offset=EQ_BLOCK_OFFSET, warn=warn)

    unknowns: dict[str, str] = {
        "byte_51": f"0x{_u8(51):02x}",
        "trailing_239": f"0x{_u8(239):02x}",
        "padding_240_242": raw[240:242].hex() if len(raw) >= 242 else "",
    }

    return ChannelBlock(
        channel=ch,
        raw=raw,
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
        muted=muted,
        unknown_bytes=unknowns,
    )
