"""Common transport interface shared by `HidTransport` (USB) and
`BleTransport` (Bluetooth LE).

Both talk the same `e0 a2 …` application protocol (see PROTOCOL.md /
docs/findings/BLE.md) and expose the same shape — a context manager with
`transact(payload: bytes) -> bytes` and `start_keepalive()` — so command code
can be written once against `Transport` and run over either link. `KeepaliveMixin`
holds the lock/stop-event/keepalive-thread machinery both implementations need;
each transport only has to implement `open()`, `close()`, and `transact()`.
"""

import logging
import threading
from typing import Protocol, runtime_checkable

from octapro.errors import TransportTimeout
from octapro.protocol.constants import KEEPALIVE_INTERVAL_S
from octapro.protocol.packet import build_keepalive

log = logging.getLogger("octapro.transport")


@runtime_checkable
class Transport(Protocol):
    """The interface commands rely on, regardless of the underlying link."""

    def __enter__(self) -> "Transport": ...

    def __exit__(self, *exc: object) -> None: ...

    def transact(self, payload: bytes) -> bytes: ...

    def start_keepalive(self) -> None: ...


class KeepaliveMixin:
    """Shared lock / stop-event / background keepalive-thread state.

    Subclasses provide their own `transact()`; this mixin drives a daemon
    thread that calls it on a fixed interval to keep the device from
    disconnecting during idle periods (long reads, monitor loops, etc.).
    Subclasses should hold `self._lock` during their own I/O so a keepalive
    tick can never interleave with a command's send+recv.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ka_thread: threading.Thread | None = None

    def transact(self, payload: bytes) -> bytes:  # pragma: no cover - overridden
        raise NotImplementedError

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

    def _stop_keepalive(self) -> None:
        self._stop.set()
        if self._ka_thread:
            self._ka_thread.join(timeout=2.0)
            self._ka_thread = None
