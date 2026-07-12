"""Transport layer for the OctaPro DSP command interface.

The device is a composite USB device; the DSP protocol lives on HID
interface 4, which has *no interrupt endpoints* — every exchange is a pair
of control transfers (SET_REPORT out, GET_REPORT in), exactly as seen in
the vendor captures (usb1.pcapng frames 107/109). Because the interface is
not HID-compliant, the OS HID stack does not bind to it (hidapi cannot see
it at all on macOS), so we drive it directly with libusb via pyusb.

All send+recv operations go through `transact()`, which holds a lock to
prevent the keepalive thread from interleaving with command reads.
"""

import logging
from typing import Any

from octapro.errors import DeviceNotFound, TransportTimeout
from octapro.protocol.constants import PID, VID
from octapro.protocol.packet import build_session_open
from octapro.transport.base import KeepaliveMixin

log = logging.getLogger("octapro.transport")

_INTERFACE = 4
_TIMEOUT_MS = 1000

# HID class control requests (report ID 0)
_SET_REPORT = 0x09
_GET_REPORT = 0x01
_RT_HOST_TO_DEV = 0x21  # class, interface
_RT_DEV_TO_HOST = 0xA1
_WVALUE_OUTPUT = 0x0200
_WVALUE_INPUT = 0x0100


class HidTransport(KeepaliveMixin):
    def __init__(self, device_index: int = 0) -> None:
        super().__init__()
        self._dev: Any = None
        self._device_index = device_index

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        try:
            import usb.core as _core
            import usb.util as _util
        except ImportError as e:
            raise ImportError(
                "The 'pyusb' package (and native libusb) is not installed.\n"
                "  Linux:  sudo apt install libusb-1.0-0 && uv sync\n"
                "  macOS:  brew install libusb && uv sync"
            ) from e

        devices = list(_core.find(find_all=True, idVendor=VID, idProduct=PID))
        if not devices:
            raise DeviceNotFound(
                f"No device found with VID=0x{VID:04x} PID=0x{PID:04x}. "
                "Is the amplifier connected and powered on?"
            )
        if self._device_index >= len(devices):
            raise DeviceNotFound(
                f"Device index {self._device_index} out of range "
                f"(found {len(devices)} matching device(s))"
            )

        dev = devices[self._device_index]
        try:
            if dev.is_kernel_driver_active(_INTERFACE):
                dev.detach_kernel_driver(_INTERFACE)
        except NotImplementedError:
            pass  # macOS: not supported and not needed — interface 4 is unclaimed
        _util.claim_interface(dev, _INTERFACE)
        self._dev = dev
        log.debug(
            "Opened USB device %s (index %d), claimed interface %d",
            dev.product, self._device_index, _INTERFACE,
        )
        # The device refuses READ_BLOCK with an ee55 ACK until this is sent
        resp = self.transact(bytes(build_session_open()))
        log.debug("Session open ack: %s", resp[:4].hex(" "))

    def close(self) -> None:
        self._stop_keepalive()
        if self._dev:
            import usb.util as _util

            _util.release_interface(self._dev, _INTERFACE)
            _util.dispose_resources(self._dev)
            self._dev = None
            log.debug("USB device closed")

    def __enter__(self) -> "HidTransport":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def transact(self, payload: bytes) -> bytes:
        """Atomic send + recv, protected by lock (keepalive-safe)."""
        assert len(payload) == 256, f"payload must be 256 bytes, got {len(payload)}"
        import usb.core as _core

        with self._lock:
            try:
                self._dev.ctrl_transfer(
                    _RT_HOST_TO_DEV, _SET_REPORT, _WVALUE_OUTPUT, _INTERFACE,
                    payload, timeout=_TIMEOUT_MS,
                )
                data = self._dev.ctrl_transfer(
                    _RT_DEV_TO_HOST, _GET_REPORT, _WVALUE_INPUT, _INTERFACE,
                    256, timeout=_TIMEOUT_MS,
                )
            except _core.USBTimeoutError as e:
                raise TransportTimeout(f"No response from device: {e}") from e
        if not len(data):
            raise TransportTimeout("Empty GET_REPORT response from device")
        return bytes(data)
