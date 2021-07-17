import httpx

from ..queue import EventMessage, EventTypes
from .base import SXMLoopedWorker

__all__ = ["StatusWorker"]

CHECK_INTERVAL = 30


class StatusWorker(SXMLoopedWorker):
    NAME = "status_check"

    _ip: str
    _port: int
    _delay: float = 30.0
    _failures: int = 0

    def __init__(self, port: int, ip: str, *args, **kwargs):

        super().__init__(*args, **kwargs)

        if ip == "0.0.0.0":  # nosec
            ip = "127.0.0.1"

        self._ip = ip
        self._port = port

    def loop(self):
        self.check_sxm()

    def check_sxm(self):
        if self._state.sxm_running:
            self._log.debug("Checking SXM Client")
            r = httpx.get(f"http://{self._ip}:{self._port}/channels/")

            if r.is_error:
                # adjust delay to check more often
                self._delay = 5.0
                self._failures += 1
                if self._failures > 3:
                    self.push_event(
                        EventMessage(
                            self.name, EventTypes.RESET_SXM, "bad status check"
                        )
                    )
            else:
                self._delay = 30.0
                self._failures = 0
                self.push_event(
                    EventMessage(self.name, EventTypes.UPDATE_CHANNELS, r.json())
                )
