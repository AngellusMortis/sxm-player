import os
from bdb import BdbQuit

from sxm_player.queue import EventMessage, EventTypes
from sxm_player.workers.base import InterruptableWorker

__all__ = ["DebugWorker"]


class DebugWorker(InterruptableWorker):
    """DebugWorker to be used for development"""

    _num: int = 0

    def run(self) -> None:
        try:
            self.debug()
        except BdbQuit:
            self._log.error("No debugger to break for")

    def debug(self):
        self.nothing_to_see_here()

    def nothing_to_see_here(self):
        breakpoint()

    def play_channel(self, channel_id: str, protocol: str = "udp"):
        self._num += 1

        player_name = f"debug_player_{channel_id}{self._num}"
        filename = os.path.abspath(f"{player_name}.mp3")
        self.push_event(
            EventMessage(
                self.name,
                EventTypes.DEBUG_START_PLAYER,
                (player_name, channel_id, filename, protocol),
            )
        )

    def stop_player(self, player_name, kill_hls=True):
        self.push_event(
            EventMessage(self.name, EventTypes.DEBUG_STOP_PLAYER, player_name)
        )

        if kill_hls:
            self.kill_hls()

    def trigger_hls(self, channel_id, protocol="udp"):
        self.push_event(
            EventMessage(
                self.name, EventTypes.TRIGGER_HLS_STREAM, (channel_id, protocol)
            )
        )

    def kill_hls(self):
        self.push_event(EventMessage(self.name, EventTypes.KILL_HLS_STREAM, None))
