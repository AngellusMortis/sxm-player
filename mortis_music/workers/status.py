import requests

from .base import SXMLoopedWorker
from ..queue import EventMessage

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
        if self._sxm_running:
            self._log.debug("Checking SiriusXM Client")
            r = requests.get(f"http://{self._ip}:{self._port}/channels/")

            if not r.ok:
                self.push_event(
                    EventMessage(
                        self.name,
                        EventMessage.RESET_SXM_EVENT,
                        "bad status check",
                    )
                )
            else:
                self.push_event(
                    EventMessage(
                        self.name, EventMessage.UPDATE_CHANNELS_EVENT, r.json()
                    )
                )
