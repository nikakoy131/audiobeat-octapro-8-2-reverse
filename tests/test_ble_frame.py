"""Offline tests for octapro.transport.ble_frame — no bleak, no hardware.

Builds a synthetic channel-block response in both the USB InPacket layout and
the BLE AE02 layout (see ble_frame.py module docstring for the byte-offset
relationship) and proves reassemble()+normalize_response() turns fragmented
BLE notifications back into something InPacket/parse_channel_block decode
identically to the USB response.
"""

import struct

from octapro.protocol.channel import BLOCK_LEN, parse_channel_block
from octapro.protocol.constants import STATUS_CHANNEL
from octapro.protocol.packet import InPacket
from octapro.transport.ble_frame import (
    ACK_PREFIXES,
    expected_len,
    is_ack_frame,
    normalize_response,
    reassemble,
)


def _channel_block(gain_db: float = -6.0, speaker_type: int = 0x06) -> bytes:
    data = bytearray(BLOCK_LEN)
    struct.pack_into("<f", data, 31, gain_db)
    struct.pack_into("<f", data, 39, 80.0)  # HPF
    struct.pack_into("<f", data, 45, 3500.0)  # LPF
    data[52] = speaker_type
    for i in range(31):
        off = 53 + i * 6
        struct.pack_into("<f", data, off, 1000.0)
        data[off + 4] = 0x78  # 0 dB
        data[off + 5] = 0x0A  # default Q
    return bytes(data)


def _usb_response(ch: int, data: bytes) -> bytes:
    """A synthetic USB InPacket-layout response: status+magic+len+addr+data."""
    addr = 0x00B7 + ch * 0x0100
    return (
        struct.pack("<H", STATUS_CHANNEL)
        + b"\xe0\xa2"
        + struct.pack("<H", len(data))
        + struct.pack("<H", addr)
        + data
    )


def _ble_response(ch: int, data: bytes) -> bytes:
    """A synthetic BLE AE02-layout response for the same read.

    Per docs/findings/BLE.md "Response framing": total wire length =
    u16_LE(datalen_field) + 4, and a live CH1 read had datalen_field=242
    (same wire value USB reports) but only 246 total bytes arrived — i.e.
    the transmitted block is 2 bytes shorter than USB's (240 vs 242). Those
    2 bytes are channel.py's documented [240:242] padding zeros, so this
    doesn't lose any decoded field; `parse_channel_block` decodes it
    identically either way (confirmed live, per BLE.md).
    """
    addr = 0x00B7 + ch * 0x0100
    assert data[-2:] == b"\x00\x00", "test fixture must end in the documented padding zeros"
    return b"\xe0\xa2" + struct.pack("<H", len(data)) + struct.pack("<H", addr) + data[:-2]


def _chunks(buf: bytes, size: int) -> list[bytes]:
    return [buf[i : i + size] for i in range(0, len(buf), size)]


class TestIsAckFrame:
    def test_known_ack_prefixes_detected(self):
        for prefix in ACK_PREFIXES:
            assert is_ack_frame(prefix + b"\x00\x00")

    def test_data_frame_not_ack(self):
        assert not is_ack_frame(b"\xe0\xa2\x01\x00\xb7\x01\x00")


class TestExpectedLen:
    def test_short_buffer_returns_none(self):
        assert expected_len(b"\xe0\xa2\x01") is None

    def test_wrong_magic_returns_none(self):
        assert expected_len(b"\xff\xff\x01\x00") is None

    def test_computed_from_header(self):
        # data_len=242 at [2:4] -> total = 242 + 4
        buf = b"\xe0\xa2" + struct.pack("<H", 242)
        assert expected_len(buf) == 246


class TestReassembleAndNormalize:
    def test_full_channel_block_roundtrips_and_matches_usb_decode(self):
        ch = 1
        data = _channel_block(gain_db=-7.0, speaker_type=0x06)
        usb_resp = _usb_response(ch, data)
        ble_frame_expected = _ble_response(ch, data)

        # Fragment as AE02 notifications would arrive (small MTU chunks),
        # with an ACK frame interleaved before the data starts.
        notifications = [ACK_PREFIXES[1] + b"\x00" * 6, *_chunks(ble_frame_expected, 20)]
        reassembled = reassemble(notifications)
        assert reassembled == ble_frame_expected

        normalized = normalize_response(reassembled)
        ip = InPacket(normalized)
        assert ip.magic == b"\xe0\xa2"
        assert ip.addr == 0x00B7 + ch * 0x0100
        assert ip.data == data[:-2]  # BLE drops the trailing [240:242] padding zeros

        # The decoded channel block is identical whichever path it came from —
        # the 2 dropped bytes are pure padding (channel.py [240:242]).
        via_ble = parse_channel_block(ip.data, ch=ch)
        via_usb = parse_channel_block(InPacket(usb_resp).data, ch=ch)
        assert via_ble.gain_db == via_usb.gain_db == -7.0
        assert via_ble.hpf_freq_hz == via_usb.hpf_freq_hz
        assert via_ble.speaker_type_byte == via_usb.speaker_type_byte == 0x06
        assert via_ble.eq_bands == via_usb.eq_bands

    def test_ack_only_stream_does_not_reassemble(self):
        assert reassemble([ACK_PREFIXES[0] + b"\x00" * 6]) is None

    def test_incomplete_stream_returns_none(self):
        ble_frame = _ble_response(1, _channel_block())
        # withhold the last chunk
        chunks = _chunks(ble_frame, 20)[:-1]
        assert reassemble(chunks) is None

    def test_extra_trailing_bytes_are_truncated_to_expected_len(self):
        ble_frame = _ble_response(1, _channel_block())
        reassembled = reassemble([ble_frame + b"\x00\x00\x00"])
        assert reassembled == ble_frame
