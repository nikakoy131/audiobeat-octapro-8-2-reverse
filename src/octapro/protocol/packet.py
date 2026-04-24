"""Build OUT packets and parse IN packets for the OctaPro HID protocol."""

import struct
from dataclasses import dataclass, field

from octapro.protocol.constants import (
    CHANNEL_ADDR_BASE,
    CHANNEL_ADDR_STRIDE,
    CMD_WRITE_DSP,
    KNOWN_STATUSES,
    REG_KEEPALIVE,
    WRITE_DSP_TRAILER,
)

# ---------------------------------------------------------------------------
# Addressing
# ---------------------------------------------------------------------------

def channel_addr(ch: int) -> int:
    """Return DSP channel base address for ch=1..10."""
    if not 1 <= ch <= 10:
        raise ValueError(f"channel must be 1..10, got {ch}")
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
    """CMD 0x05 READ_BLOCK. ch=0 reads master; ch=1..10 reads DSP channels."""
    pkt = _base_packet(0x05, 0x00B0, (0x04 << 8) | ch)
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


def build_dsp_commit(ch: int) -> bytearray:
    """CMD 0x05 with sub=0x01 — commit trigger to apply a WRITE_DSP batch."""
    addr = channel_addr(ch)
    pkt = _base_packet(0x05, addr, 0x01)
    pkt[8] = compute_checksum(pkt)
    return pkt


def build_keepalive() -> bytearray:
    return build_write_param(0x00B0, REG_KEEPALIVE, csum=0x94)


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
