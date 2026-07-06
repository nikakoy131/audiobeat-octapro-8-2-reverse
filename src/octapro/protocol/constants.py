from typing import Final

VID: Final = 0x8888
PID: Final = 0x1234

MAGIC: Final = bytes([0xE0, 0xA2])

# Commands
CMD_WRITE_PARAM: Final = 0x04
CMD_READ_BLOCK: Final = 0x05
CMD_UNKNOWN_08: Final = 0x08
CMD_WRITE_DSP: Final = 0x0A
CMD_UNKNOWN_1C: Final = 0x1C

KNOWN_CMDS: Final[frozenset[int]] = frozenset({CMD_WRITE_PARAM, CMD_READ_BLOCK, CMD_WRITE_DSP})

# CMD 0x04 registers
REG_FIRMWARE: Final = 0x80F0
REG_KEEPALIVE: Final = 0xA515
REG_INIT: Final = 0x9909

# CMD 0x05 session open (usb1.pcapng frame 107) — must be sent once after
# connecting or the device answers READ_BLOCK with a short ee55 refusal ACK
SESSION_OPEN_ADDR: Final = 0x00B7
SUB_SESSION_OPEN: Final = 0x1103

# CMD 0x08 is the volume-write command (float32 dB at [7:11], checksum at [11]),
# live-captured 2026-07-05/06 via the uhid shim from the vendor app's own
# fader traffic. The sub-byte at [6] + addr select the target:
#   sub 0x0c, addr 0x00b7  -> master (Main) volume
#   sub 0x03, addr 0xNNb7  -> channel N output fader/gain
# CMD 0x08's other sub-family (0x06, e.g. sub=0206/8206) is unrelated and
# still unidentified — CMD_UNKNOWN_08 covers that one.
CMD_WRITE_MASTER_VOLUME: Final = 0x08  # == the volume-write command; kept name for back-compat
SUB_MASTER_VOLUME: Final = 0x0C
SUB_CHANNEL_GAIN: Final = 0x03
# sub 0x04, addr 0xNNb7 -> channel N time-alignment delay, float32 milliseconds
# (live-verified CH2 -> 1.512 ms, 2026-07-06). The app's cm/inch modes convert
# to ms before sending.
SUB_CHANNEL_DELAY: Final = 0x04

# CMD 0x05 mute toggle, live-captured 2026-07-06 via the uhid shim
# (docs/LINUX_UHID_SHIM_PLAN.md). byte[7]=state (1=mute, 0=unmute); addr
# picks the target (0x00b7=master, 0xNNb7=channel N). Master and per-channel
# use DIFFERENT sub-bytes at byte[6] — an asymmetry, but both live-verified:
#   master  (ch0):  byte[6]=0x0d
#   channel (chN):  byte[6]=0x01  (LE u16 sub 0x0101 mute / 0x0001 unmute)
# The per-channel form is what earlier notes mislabelled a "commit trigger".
SUB_MUTE_MASTER: Final = 0x0D
SUB_MUTE_CHANNEL: Final = 0x01
MUTE_ON: Final = 0x01
MUTE_OFF: Final = 0x00

# CMD 0x05 phase invert, live-captured 2026-07-06 (channel 6). Same channel-
# flag family as mute: addr=0xNNb7, byte[6]=selector, byte[7]=state. byte[7]:
# 1 = 180° (inverted), 0 = 0° (normal).
SUB_PHASE: Final = 0x02

# CMD 0x05 EQ pass/bypass, live-captured 2026-07-06 (channel 7). Channel-flag
# selector 0x07: byte[7]=1 bypasses the channel EQ, 0 engages it.
SUB_EQ_PASS: Final = 0x07

# CMD 0x1c bridge (CH7+CH8 — the only bridgeable pair on this device),
# live-captured 2026-07-06. addr=0x00b7, byte[6]=sub 0x28, then a fixed
# 23-byte "walking-bit" payload [8:31] with the bridge state in byte[19]
# (bit 0x80: set = bridged), checksum at byte[31] = (sum(pkt[4:31]) - 0x20).
# The app also emits a companion sub-0x21 packet that never changes with
# bridge state (a UI-sync/refresh, also seen during enumeration), so it is
# not part of the write. Checksum spans [4:31], unlike the short commands'
# [4:13] — compute it explicitly, not via compute_checksum().
CMD_BRIDGE: Final = 0x1C
SUB_BRIDGE: Final = 0x28
BRIDGE_STATE_OFFSET: Final = 19       # byte[19]
BRIDGE_STATE_BIT: Final = 0x80        # OR'd into byte[19] when bridged
BRIDGE_CHECKSUM_OFFSET: Final = 31    # byte[31]
# Fixed payload [8:31] captured live (unbridged base; byte[19]=0x40 here, at
# index 11 of this slice). build_bridge sets/clears the 0x80 bit on top.
BRIDGE_PAYLOAD_TEMPLATE: Final = bytes([
    0x00, 0x02, 0x00, 0x04, 0x00, 0x08, 0x00, 0x10, 0x00, 0x20, 0x00, 0x40,
    0x00, 0x80, 0x00, 0x00, 0x01, 0x00, 0x02, 0x00, 0x04, 0x00, 0x08,
])

# CMD 0x0a sub-addresses (known)
SUB_HPF_FREQ: Final = 0x05
SUB_GAIN: Final = 0x26
# EQ band write, live-captured 2026-07-06 (ch1: band 18/1 kHz +6.0 dB, and
# band 8/100 Hz -5.0 dB). One WRITE_DSP carries the whole band: the sub-byte
# at [6] selects the band slot (sub = 0x08 + (band-1), so band 1..31 -> sub
# 0x08..0x26); float32 center freq at [7:11] (settable per band); gain byte at
# [11] (db_to_byte); Q byte at [12] (default 0x0a). No [14:16] trailer, no
# commit. Gain verified on 2 bands; freq-move and Q-change not yet captured.
EQ_BAND_SUB_BASE: Final = 0x08


def eq_band_sub(band: int) -> int:
    """Sub-byte at [6] for EQ band `band` (1..31)."""
    if not 1 <= band <= EQ_BAND_COUNT:
        raise ValueError(f"band must be 1..{EQ_BAND_COUNT}, got {band}")
    return EQ_BAND_SUB_BASE + (band - 1)

# CMD 0x0a type bytes
TYPE_HPF: Final = 0x00
TYPE_GAIN: Final = 0x0A

# Known slope codes (HPF/LPF)
SLOPE_12DB: Final = 0x03
SLOPE_36DB: Final = 0x05
KNOWN_SLOPES: Final[frozenset[int]] = frozenset({SLOPE_12DB, SLOPE_36DB})

# IN status codes
STATUS_ACK_SHORT: Final = 0x0002   # magic=eebb; generic ack, also initial "not connected"
STATUS_KEEPALIVE: Final = 0x000F
STATUS_INIT: Final = 0x002F
STATUS_FIRMWARE: Final = 0x006A
STATUS_MASTER: Final = 0x008D
STATUS_CHANNEL: Final = 0x00F6
KNOWN_STATUSES: Final[frozenset[int]] = frozenset({
    STATUS_ACK_SHORT, STATUS_KEEPALIVE, STATUS_INIT,
    STATUS_FIRMWARE, STATUS_MASTER, STATUS_CHANNEL,
})

# Input source IDs — keepalive byte [11]; live-mapped 2026-07-05 by cycling
# the remote panel's source menu (IDs follow the menu order)
SOURCE_NAMES: Final[dict[int, str]] = {
    0x00: "high level",
    0x01: "low level",
    0x02: "opt",
    0x03: "USB AUDIO",
}

# Channel addressing
NUM_CHANNELS: Final = 10
CHANNEL_ADDR_BASE: Final = 0x00B7
CHANNEL_ADDR_STRIDE: Final = 0x0100

# Gain encoding
GAIN_MUTE_BYTE: Final = 0x80
GAIN_ZERO_BYTE: Final = 0x78

# Keepalive interval (device disconnects if silent > ~1s)
KEEPALIVE_INTERVAL_S: Final = 0.45

# WRITE_DSP trailer at [14:16] — meaning unknown, consistently observed
WRITE_DSP_TRAILER: Final = bytes([0x00, 0x10])

# Fixed float reference in WRITE_DSP GAIN commands (always 20000.0)
WRITE_DSP_GAIN_FLOAT_REF: Final = 20000.0

# EQ — 31 standard 1/3-octave band centers
EQ_BAND_CENTERS_HZ: Final[list[float]] = [
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
    200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
    2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000,
]

EQ_DEFAULT_Q_BYTE: Final = 0x0A
EQ_BAND_COUNT: Final = 31
EQ_BAND_STRIDE: Final = 6

# LPF "bypass" frequency used when filter is off
LPF_BYPASS_HZ: Final = 20600.0
