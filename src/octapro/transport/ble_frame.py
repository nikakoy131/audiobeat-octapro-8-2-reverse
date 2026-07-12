"""Pure BLE response-frame helpers for the OctaPro AE00 GATT bridge.

The BLE link carries the identical `e0 a2 …` protocol as USB HID (see
docs/findings/BLE.md), but the response frame is exactly the USB `InPacket`
layout minus its leading 2-byte status word:

    USB (InPacket):   status[0:2] magic[2:4] data_len[4:6] addr[6:8] block[8:]
    BLE (AE02 frame):             magic[0:2] data_len[2:4] addr[4:6] block[6:]

So a reassembled BLE frame is byte-identical to `USB response bytes[2:]` —
prepending a synthetic 2-byte status word turns it back into something
`InPacket` and every downstream parser (`parse_channel_block`,
`parse_master_block`, ...) decode unchanged. No command-layer parsing changes
are needed for BLE.

These are plain functions (no `bleak` import) so they're unit-testable
offline without the `ble` extra installed.
"""

from collections.abc import Iterable

MAGIC = b"\xe0\xa2"

# ACK/status frames the vendor app discards, not response payload
# (docs/findings/BLE.md "Response framing").
ACK_PREFIXES: tuple[bytes, ...] = (b"\xee\xbb", b"\xee\x55", b"\xbe\x70\x1d\x00", b"\xbe\x70\x22")

# Synthetic status word prepended to a reassembled BLE frame to match the USB
# InPacket layout. No parser inspects this value for correctness (only
# `InPacket.status_known` warns on an unrecognized one), so a fixed
# placeholder is used rather than trying to guess the USB-side status code.
SYNTHETIC_STATUS = b"\x00\x00"


def is_ack_frame(frame: bytes) -> bool:
    """True if `frame` is a short ACK/status notification, not response data."""
    return any(frame.startswith(p) for p in ACK_PREFIXES)


def expected_len(buf: bytes) -> int | None:
    """Total BLE response length = u16_LE(buf[2:4]) + 4, once the header is known.

    Returns None if `buf` isn't long enough yet to read the header.
    """
    if len(buf) < 4 or buf[:2] != MAGIC:
        return None
    return int.from_bytes(buf[2:4], "little") + 4


def reassemble(frames: Iterable[bytes]) -> bytes | None:
    """Concatenate AE02 notification frames into one complete e0a2 response.

    Filters ACK/status frames. Returns None if the frames never accumulate to
    the length the header declares (caller should treat that as a timeout).
    """
    buf = bytearray()
    for frame in frames:
        if is_ack_frame(frame):
            continue
        buf.extend(frame)
        n = expected_len(bytes(buf))
        if n is not None and len(buf) >= n:
            return bytes(buf[:n])
    return None


def normalize_response(ble_frame: bytes) -> bytes:
    """Re-pack a reassembled BLE frame into the USB `InPacket` byte layout."""
    return SYNTHETIC_STATUS + ble_frame
