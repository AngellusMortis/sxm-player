import requests

from ..queue import Event, EventMessage
from .base import SXMLoopedWorker

__all__ = ["StatusWorker"]

CHECK_INTERVAL = 30


class StatusWorker(SXMLoopedWorker):
    NAME = "status_check"

    _ip: str
    _port: int
    _delay: float = 30.0

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
            r = requests.get(f"http://{self._ip}:{self._port}/channels/")

            if not r.ok:
                self.push_event(
                    EventMessage(
                        self.name, Event.RESET_SXM, "bad status check"
                    )
                )
            else:
                self.push_event(
                    EventMessage(self.name, Event.UPDATE_CHANNELS, r.json())
                )
