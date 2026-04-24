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

# CMD 0x0a sub-addresses (known)
SUB_HPF_FREQ: Final = 0x05
SUB_GAIN: Final = 0x26

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
