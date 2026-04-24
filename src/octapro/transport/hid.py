"""HID transport layer wrapping cython-hidapi.

All send+recv operations go through `transact()`, which holds a lock to prevent
the keepalive thread from interleaving with command reads.
"""

import logging
import threading
from typing import Any

from octapro.errors import DeviceNotFound, TransportTimeout
from octapro.protocol.constants import KEEPALIVE_INTERVAL_S, PID, VID
from octapro.protocol.packet import build_keepalive

log = logging.getLogger("octapro.transport")

_REPORT_ID = 0x00
_READ_TIMEOUT_MS = 500


class HidTransport:
    def __init__(self, device_index: int = 0) -> None:
        self._dev: Any = None
        self._device_index = device_index
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ka_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        try:
            import hid as _hid
        except ImportError as e:
            raise ImportError(
                "The 'hid' package is not installed.\n"
                "  Linux:  sudo apt install libhidapi-dev && pip install hid\n"
                "  macOS:  brew install hidapi && pip install hid"
            ) from e

        devices = _hid.enumerate(VID, PID)
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

        self._dev = _hid.device()
        self._dev.open(VID, PID)
        prod = devices[self._device_index].get("product_string", "unknown")
        log.debug("Opened HID device: %s (index %d)", prod, self._device_index)

    def close(self) -> None:
        self._stop.set()
        if self._ka_thread:
            self._ka_thread.join(timeout=2.0)
            self._ka_thread = None
        if self._dev:
            self._dev.close()
            self._dev = None
            log.debug("HID device closed")

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
        with self._lock:
            self._dev.write(bytes([_REPORT_ID]) + payload)
            data = self._dev.read(256, timeout_ms=_READ_TIMEOUT_MS)
        if not data:
            raise TransportTimeout("No response from device (timeout after 500 ms)")
        return bytes(data)

    # ------------------------------------------------------------------
    # Keepalive
    # ------------------------------------------------------------------

    def start_keepalive(self) -> None:
        """Start background thread that sends keepalive every ~450 ms."""
        pkt = bytes(build_keepalive())
        self._stop.clear()

        def _loop() -> None:
            while not self._stop.wait(KEEPALIVE_INTERVAL_S):
                try:
                    self.transact(pkt)
                    log.debug("Keepalive sent")
                except TransportTimeout:
                    log.warning("Keepalive: no response — device may have disconnected")
                except Exception as exc:
                    log.warning("Keepalive error: %s", exc)

        self._ka_thread = threading.Thread(
            target=_loop, daemon=True, name="octapro-keepalive"
        )
        self._ka_thread.start()
        log.debug("Keepalive thread started (interval=%.2fs)", KEEPALIVE_INTERVAL_S)
