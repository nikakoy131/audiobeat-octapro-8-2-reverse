"""Build OUT packets and parse IN packets for the OctaPro HID protocol."""

import struct
from dataclasses import dataclass, field

from octapro.protocol.constants import (
    BRIDGE_CHECKSUM_OFFSET,
    BRIDGE_PAYLOAD_TEMPLATE,
    BRIDGE_STATE_BIT,
    BRIDGE_STATE_OFFSET,
    CHANNEL_ADDR_BASE,
    CHANNEL_ADDR_STRIDE,
    CMD_BRIDGE,
    CMD_READ_BLOCK,
    CMD_WRITE_DSP,
    CMD_WRITE_MASTER_VOLUME,
    KNOWN_STATUSES,
    MUTE_OFF,
    MUTE_ON,
    REG_KEEPALIVE,
    SESSION_OPEN_ADDR,
    SUB_BRIDGE,
    SUB_CHANNEL_GAIN,
    SUB_MASTER_VOLUME,
    SUB_MUTE_CHANNEL,
    SUB_MUTE_MASTER,
    SUB_PHASE,
    SUB_SESSION_OPEN,
    WRITE_DSP_TRAILER,
)

# ---------------------------------------------------------------------------
# Addressing
# ---------------------------------------------------------------------------

def channel_addr(ch: int) -> int:
    """Return DSP channel base address. ch=0 is the master (main volume);
    ch=1..10 are the DSP channels. Master gain write live-verified 2026-07-04."""
    if not 0 <= ch <= 10:
        raise ValueError(f"channel must be 0..10 (0=master), got {ch}")
    return CHANNEL_ADDR_BASE + ch * CHANNEL_ADDR_STRIDE


# ---------------------------------------------------------------------------
# Checksum
# ---------------------------------------------------------------------------

def compute_checksum(pkt: bytes | bytearray) -> int:
    """Universal checksum: (sum(pkt[4:13]) - 0x20) & 0xFF.

    For CMD 0x0a the result goes at byte [13]; for all others it goes at [8].
    """
    return (sum(pkt[4:13]) - 0x20) & 0xFF


# ---------------------------------------------------------------------------
# OUT packet builders
# ---------------------------------------------------------------------------

def _base_packet(cmd: int, addr: int, sub: int) -> bytearray:
    pkt = bytearray(256)
    pkt[0], pkt[1] = 0xE0, 0xA2
    pkt[2] = cmd
    pkt[3] = 0x00
    struct.pack_into("<H", pkt, 4, addr)
    struct.pack_into("<H", pkt, 6, sub)
    return pkt


def build_write_param(addr: int, reg: int, csum: int | None = None) -> bytearray:
    """CMD 0x04 WRITE_PARAM. Pass explicit csum for observed magic values."""
    pkt = _base_packet(0x04, addr, reg)
    pkt[8] = csum if csum is not None else compute_checksum(pkt)
    return pkt


def build_read_channel(ch: int) -> bytearray:
    """CMD 0x05 READ_BLOCK. ch=0 reads master; ch=1..10 reads DSP channels.

    Wire bytes at [6:8] are 04 <ch> (usb1.pcapng frame 119) — as a LE u16
    sub that is (ch << 8) | 0x04; the device refuses the swapped form.
    """
    pkt = _base_packet(0x05, 0x00B0, (ch << 8) | 0x04)
    pkt[8] = 0x94 + ch  # observed magic from captures
    return pkt


def build_write_dsp(
    addr: int,
    sub_byte: int,
    float_val: float,
    param_byte: int,
    type_byte: int,
) -> bytearray:
    """CMD 0x0a WRITE_DSP. Checksum stored at [13] (not [8])."""
    pkt = bytearray(256)
    pkt[0], pkt[1] = 0xE0, 0xA2
    pkt[2] = CMD_WRITE_DSP
    pkt[3] = 0x00
    struct.pack_into("<H", pkt, 4, addr)
    pkt[6] = sub_byte
    struct.pack_into("<f", pkt, 7, float_val)
    pkt[11] = param_byte
    pkt[12] = type_byte
    pkt[13] = compute_checksum(pkt)
    pkt[14] = WRITE_DSP_TRAILER[0]
    pkt[15] = WRITE_DSP_TRAILER[1]
    return pkt


def _build_volume_write(addr: int, sub_byte: int, db: float) -> bytearray:
    """CMD 0x08 volume write — float32 dB at [7:11], checksum at [11].

    The one command the vendor app uses for both the Main fader and the
    per-channel output faders (docs/LINUX_UHID_SHIM_PLAN.md). addr + sub_byte
    select the target; no commit packet follows (applies immediately).

    Checksum sits at [11], right after the float, rather than [8] or [13]
    like the other commands — but it's the same universal formula, and
    compute_checksum(pkt) still gives the right answer here because bytes
    [11:13] are still zero when it's called (summing pkt[4:13] with two
    trailing zeros equals summing just pkt[4:11]).
    """
    pkt = bytearray(256)
    pkt[0], pkt[1] = 0xE0, 0xA2
    pkt[2] = CMD_WRITE_MASTER_VOLUME  # 0x08 — the volume-write command
    pkt[3] = 0x00
    struct.pack_into("<H", pkt, 4, addr)
    pkt[6] = sub_byte
    struct.pack_into("<f", pkt, 7, db)
    pkt[11] = compute_checksum(pkt)
    return pkt


def build_write_master_volume(volume_db: float) -> bytearray:
    """CMD 0x08 sub 0x0c — master (Main) volume write.

    Live-captured 2026-07-05 via the uhid shim. Byte-perfect across 17
    samples spanning -35.9..-0.98 dB, each independently checksum-verified;
    a final live check (drag to "-20.0 dB" on the app's UI) decoded to
    -20.02 dB.
    """
    return _build_volume_write(channel_addr(0), SUB_MASTER_VOLUME, volume_db)


def build_channel_gain(ch: int, db: float) -> bytearray:
    """CMD 0x08 sub 0x03 — channel N output fader/gain (ch=1..10).

    Live-captured 2026-07-06 by dragging CH3's fader to -6.0 dB:
        e0 a2 08 00 b7 03 03 00 00 c0 c0 1d   (float32 = -6.00 dB)
    Same command family as the master volume; only addr and the sub-byte
    differ. This is the command the app actually uses for faders — NOT the
    CMD 0x0a WRITE_DSP path that build_write_dsp / the older `write gain`
    used (that was inferred from pcaps and never matched app fader traffic).
    """
    if ch == 0:
        raise ValueError("ch=0 is the master fader — use build_write_master_volume")
    return _build_volume_write(channel_addr(ch), SUB_CHANNEL_GAIN, db)


def build_channel_flag(ch: int, selector: int, on: bool) -> bytearray:
    """CMD 0x05 per-channel boolean flag (the mute / phase command family).

    Live-captured 2026-07-06 via the uhid shim (docs/LINUX_UHID_SHIM_PLAN.md).
    All members share one wire shape:
        e0 a2 05 00 b7 NN <selector> <state> <csum>
    where addr `0xNNb7` = channel_addr(ch), byte[6]=selector picks the
    parameter, byte[7]=state (1=on, 0=off), byte[8]=checksum.

    Known selectors (byte[6]):
        0x01  per-channel mute       0x02  phase invert
        0x0d  master mute (ch0 only)
    """
    pkt = _base_packet(CMD_READ_BLOCK, channel_addr(ch), 0)
    pkt[6] = selector
    pkt[7] = MUTE_ON if on else MUTE_OFF
    pkt[8] = compute_checksum(pkt)
    return pkt


def build_mute(ch: int, mute: bool) -> bytearray:
    """CMD 0x05 mute / unmute a channel (ch=0 = master/Main, 1..10 = DSP).

    Live-captured 2026-07-06 via the uhid shim. **Master and per-channel mute
    use different selector bytes** — an asymmetry, but both directly verified:

        master  (ch0): e0 a2 05 00 b7 00 0d 01 a5   byte[6]=0x0d
        channel (chN): e0 a2 05 00 b7 0N 01 01 ..   byte[6]=0x01

    byte[7] is the state (1=mute, 0=unmute). Verified byte-perfect: master
    on/off, and channels 2/6/10 mute + channel 6 unmute.

    The per-channel form (byte[6]=0x01, i.e. LE u16 sub 0x0101/0x0001) is
    the command PROTOCOL.md previously mislabelled a "DSP commit trigger" —
    see build_dsp_commit's note; those captures were mute toggles.
    """
    selector = SUB_MUTE_MASTER if ch == 0 else SUB_MUTE_CHANNEL
    return build_channel_flag(ch, selector, mute)


def build_phase(ch: int, invert: bool) -> bytearray:
    """CMD 0x05 phase invert for a channel (byte[6]=0x02, 1=180°, 0=0°).

    Live-captured 2026-07-06 by toggling channel 6's phase in the app:
        180°: e0 a2 05 00 b7 06 02 01 a0
          0°: e0 a2 05 00 b7 06 02 00 9f
    Both byte-perfect incl. checksum. Only channel 6 is live-verified; other
    channels follow from the shared channel-flag addressing.
    """
    return build_channel_flag(ch, SUB_PHASE, invert)


def build_bridge(bridged: bool) -> bytearray:
    """CMD 0x1c — bridge CH7+CH8 (the only bridgeable pair on this device).

    Live-captured 2026-07-06 by toggling the bridge in the app. Byte-perfect
    for both states:
        bridged:   e0 a2 1c 00 b7 00 28 01 ...00 c0 00 80... 4d
        unbridged: e0 a2 1c 00 b7 00 28 01 ...00 40 00 80... cd
    The payload is a fixed 23-byte template; only byte[19] carries the state
    (bit 0x80 set = bridged) and the checksum at byte[31] follows. Unlike the
    short commands, the checksum spans pkt[4:31].
    """
    pkt = bytearray(256)
    pkt[0], pkt[1] = 0xE0, 0xA2
    pkt[2] = CMD_BRIDGE
    pkt[3] = 0x00
    struct.pack_into("<H", pkt, 4, channel_addr(0))
    pkt[6] = SUB_BRIDGE
    pkt[7] = 0x01
    pkt[8 : 8 + len(BRIDGE_PAYLOAD_TEMPLATE)] = BRIDGE_PAYLOAD_TEMPLATE
    if bridged:
        pkt[BRIDGE_STATE_OFFSET] |= BRIDGE_STATE_BIT
    pkt[BRIDGE_CHECKSUM_OFFSET] = (sum(pkt[4:BRIDGE_CHECKSUM_OFFSET]) - 0x20) & 0xFF
    return pkt


def build_dsp_commit(ch: int) -> bytearray:
    """CMD 0x05 with sub=0x01 — believed to commit a WRITE_DSP batch.

    SUSPECT (2026-07-06): this packet (LE u16 sub 0x0001) is byte-identical
    to a per-channel UNMUTE (see build_mute / PROTOCOL.md "Mute write").
    Master volume (CMD 0x08) was shown to apply with no commit at all, so it
    is unclear whether WRITE_DSP really needs this step or whether the
    "commit" seen in captures was just the app unmuting the channel. Kept as
    the HPF/gain write path still uses it; re-verify against a live device
    before relying on it.
    """
    addr = channel_addr(ch)
    pkt = _base_packet(0x05, addr, 0x01)
    pkt[8] = compute_checksum(pkt)
    return pkt


def build_keepalive() -> bytearray:
    return build_write_param(0x00B0, REG_KEEPALIVE, csum=0x94)


def build_session_open() -> bytearray:
    """CMD 0x05 addr=0x00b7 sub=0x1103 — first packet the vendor app sends.

    Without it the device answers READ_BLOCK with a short ee55 refusal ACK
    instead of the channel block (verified against live device).
    """
    pkt = _base_packet(0x05, SESSION_OPEN_ADDR, SUB_SESSION_OPEN)
    pkt[8] = compute_checksum(pkt)
    return pkt


def parse_keepalive_knob_vol(resp: bytes) -> tuple[float, bool]:
    """Decode knob-vol (remote-knob volume) from a keepalive IN packet (0x000f).

    The keepalive response doubles as a knob-vol readback: float32 LE dB
    at [12:16], live-verified against the remote knob across its full range
    (knob 0 = -60.0 dB ... knob 35 = +6.0 dB, audio-taper curve between).
    Resolved 2026-07-05: this is THE master volume register — the remote
    knob and the software Main fader both control it (manual p.14: the
    knob "adjusts the main volume (0-35)"; p.10: Main range +6…−60 dB).
    The CH0 block float at [9:13] is the same value.

    Byte [16] is a response checksum: (sum(resp[8:16]) - 0x70) & 0xFF —
    fits all live samples so far (n=3); returned flag is False on mismatch.
    """
    volume_db: float = struct.unpack_from("<f", resp, 12)[0]
    trailer_ok = resp[16] == (sum(resp[8:16]) - 0x70) & 0xFF
    return volume_db, trailer_ok


def parse_keepalive_source(resp: bytes) -> int:
    """Input source ID from a keepalive IN packet, byte [11].

    Live-mapped 2026-07-05 by cycling the remote panel's source menu:
    0x00=high level, 0x01=low level, 0x02=opt, 0x03=USB AUDIO (menu order).
    Each source stores its own knob-vol level — the volume float [12:16]
    is the *current source's* level and changes on source switch.
    """
    return resp[11]


# ---------------------------------------------------------------------------
# IN packet parser
# ---------------------------------------------------------------------------

@dataclass
class InPacket:
    raw: bytes
    status: int = field(init=False)
    magic: bytes = field(init=False)
    data_len: int = field(init=False)
    addr: int = field(init=False)
    data: bytes = field(init=False)

    def __post_init__(self) -> None:
        r = self.raw
        self.status = struct.unpack_from("<H", r, 0)[0] if len(r) >= 2 else 0
        self.magic = r[2:4] if len(r) >= 4 else b""
        self.data_len = struct.unpack_from("<H", r, 4)[0] if len(r) >= 6 else 0
        self.addr = struct.unpack_from("<H", r, 6)[0] if len(r) >= 8 else 0
        self.data = r[8:] if len(r) >= 8 else b""

    @property
    def is_ack_short(self) -> bool:
        return self.status == 0x0002 and self.magic == b"\xEE\xBB"

    @property
    def status_known(self) -> bool:
        return self.status in KNOWN_STATUSES
