"""BLE transport — the OctaPro `0xAE00` GATT vendor-serial bridge.

The device's Bluetooth control path (docs/findings/BLE.md) carries the same
`e0 a2 …` protocol as USB HID: write the short (unpadded) packet to
characteristic `AE10` with response, and reassemble `AE02` notifications into
the response. Distilled from `scripts/ble_probe.py` (read) and
`scripts/ble_mute_test.py` (write), both live-verified 2026-07-12.

`bleak` is only imported lazily inside `open()` so importing this module (and
running the test suite) never requires the optional `ble` extra — mirrors
`transport/hid.py`'s lazy `pyusb` import.
"""

import asyncio
import contextlib
import logging
import threading
from typing import Any

from octapro.errors import DeviceNotFound, TransportTimeout
from octapro.protocol.packet import build_session_open
from octapro.transport.base import KeepaliveMixin
from octapro.transport.ble_frame import expected_len, is_ack_frame, normalize_response

log = logging.getLogger("octapro.transport")

DEVICE_NAME = "AB OctaPro BLE"

WRITE_CHAR = "0000ae10-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR = "0000ae02-0000-1000-8000-00805f9b34fb"

_CONNECT_TIMEOUT_S = 10.0
_RESPONSE_TIMEOUT_S = 3.0


def _import_bleak() -> Any:
    try:
        import bleak
    except ImportError as e:
        raise ImportError(
            "The 'bleak' package is not installed.\n"
            "  Install the BLE extra:  uv sync --extra ble"
        ) from e
    return bleak


class BleTransport(KeepaliveMixin):
    """Talks to the device over the `AE00` BLE GATT bridge.

    `bleak` is async-only, so this runs its own asyncio event loop on a
    background thread; `transact()` marshals each call onto that loop and
    blocks the caller until the reassembled response is ready, giving the
    same synchronous `transact(payload) -> bytes` contract as `HidTransport`.
    """

    def __init__(self, address: str | None = None, name: str = DEVICE_NAME) -> None:
        super().__init__()
        self._address = address
        self._name = name
        self._client: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._buf = bytearray()
        self._response_ready: asyncio.Event | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        bleak = _import_bleak()

        self._loop = asyncio.new_event_loop()
        loop = self._loop
        self._loop_thread = threading.Thread(
            target=loop.run_forever, daemon=True, name="octapro-ble-loop"
        )
        self._loop_thread.start()

        async def _connect() -> None:
            self._response_ready = asyncio.Event()
            address = self._address
            if address is None:
                device = await bleak.BleakScanner.find_device_by_name(
                    self._name, timeout=_CONNECT_TIMEOUT_S
                )
                if device is None:
                    raise DeviceNotFound(
                        f"No BLE peripheral named {self._name!r} found. "
                        "Run `octaproctl ble scan` and `octaproctl ble connect`, "
                        "or pass an explicit address."
                    )
                address = device.address
            client = bleak.BleakClient(address, timeout=_CONNECT_TIMEOUT_S)
            try:
                # bleak's `timeout` kwarg only bounds device *discovery*, not
                # the connect attempt itself — on the BlueZ backend a
                # nonexistent/unreachable address can otherwise hang far
                # longer than _CONNECT_TIMEOUT_S (observed: past 60s). Wrap
                # explicitly for a hard, predictable deadline.
                await asyncio.wait_for(client.connect(), timeout=_CONNECT_TIMEOUT_S)
            except TimeoutError as e:
                raise DeviceNotFound(
                    f"Timed out connecting to BLE device {address} "
                    f"(no response within {_CONNECT_TIMEOUT_S:.0f}s)"
                ) from e
            except Exception as e:
                raise DeviceNotFound(f"Could not connect to BLE device {address}: {e}") from e
            await client.start_notify(NOTIFY_CHAR, self._on_notify)
            self._client = client

        self._run_coro(_connect())
        log.debug("Opened BLE device %s", self._address or self._name)
        # The device refuses READ_BLOCK with an ee55 ACK until this is sent
        resp = self.transact(bytes(build_session_open()))
        log.debug("Session open ack: %s", resp[:4].hex(" "))

    def close(self) -> None:
        self._stop_keepalive()
        if self._client is not None and self._loop is not None:
            with contextlib.suppress(Exception):
                self._run_coro(self._client.disconnect())
            self._client = None
        if self._loop is not None:
            loop = self._loop
            loop.call_soon_threadsafe(loop.stop)
            if self._loop_thread:
                self._loop_thread.join(timeout=2.0)
            self._loop = None
            self._loop_thread = None
            log.debug("BLE device closed")

    def __enter__(self) -> "BleTransport":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        """bleak notification callback — runs on the loop thread."""
        frame = bytes(data)
        if is_ack_frame(frame):
            return
        self._buf.extend(frame)
        n = expected_len(bytes(self._buf))
        if n is not None and len(self._buf) >= n and self._response_ready is not None:
            self._response_ready.set()

    def _run_coro(self, coro: Any) -> Any:
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def transact(self, payload: bytes) -> bytes:
        """Atomic send + recv, protected by lock (keepalive-safe).

        Accepts the same 256-byte zero-padded payload as `HidTransport` for a
        uniform command-layer interface; internally it is stripped to the
        short (unpadded) form BLE expects, and the response is re-packed to
        the USB `InPacket` byte layout (see `ble_frame.normalize_response`).
        """
        assert len(payload) == 256, f"payload must be 256 bytes, got {len(payload)}"
        short = payload.rstrip(b"\x00")

        async def _write_and_wait() -> bytes:
            assert self._response_ready is not None
            self._buf.clear()
            self._response_ready.clear()
            await self._client.write_gatt_char(WRITE_CHAR, short, response=True)
            try:
                await asyncio.wait_for(self._response_ready.wait(), timeout=_RESPONSE_TIMEOUT_S)
            except TimeoutError as e:
                raise TransportTimeout(f"No response from device: {e}") from e
            return bytes(self._buf)

        with self._lock:
            ble_frame = self._run_coro(_write_and_wait())
        if not ble_frame:
            raise TransportTimeout("Empty response from BLE device")
        return normalize_response(ble_frame)
