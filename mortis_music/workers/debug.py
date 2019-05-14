import os
import time
from typing import Optional

from .base import InterruptableWorker, ComboLoopedWorker, FFmpegPlayer

from ..queue import EventMessage

__all__ = ["DebugWorker", "DebugHLSPlayer"]

FFMPEG_COMMAND = "ffmpeg -y -loglevel fatal -f mpegts -i {} {}"


class DebugWorker(InterruptableWorker):
    """ SiriusXMProxy Server for Discord bot to interface with """

    NAME = "debug"

    _num: int = 0

    def run(self) -> None:
        self.debug()

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
                EventMessage.START_DEBUG_PLAYER,
                (player_name, channel_id, filename, protocol),
            )
        )

    def stop_player(self, player_name, kill_hls=True):
        self.push_event(
            EventMessage(
                self.name, EventMessage.STOP_DEBUG_PLAYER, player_name
            )
        )

        if kill_hls:
            self.kill_hls()

    def trigger_hls(self, channel_id, protocol="udp"):
        self.push_event(
            EventMessage(
                self.name,
                EventMessage.TRIGGER_HLS_STREAM,
                (channel_id, protocol),
            )
        )

    def kill_hls(self):
        self.push_event(
            EventMessage(self.name, EventMessage.KILL_HLS_STREAM, None)
        )


class DebugHLSPlayer(ComboLoopedWorker, FFmpegPlayer):
    channel_id: Optional[str]
    stream_protocol: str

    _event_cooldown: float = 0

    def __init__(
        self, filename: str, *args, stream_protocol: str = "udp", **kwargs
    ):
        super().__init__(*args, **kwargs)

        self._sxm_running = True
        self.channel_id = self._state.stream_channel
        self.stream_protocol = stream_protocol
        self.filename = filename

        if self.channel_id is None:
            raise RuntimeError("No channel_id or stream_url provided")

    def loop(self):
        if self._sxm_running and self._state.stream_url is not None:
            self._valid_stream_loop()
        else:
            self._invalid_stream_loop()

    def _valid_stream_loop(self):
        if self.process is None:
            if self._state.stream_url is not None:
                self._log.info(
                    f"Starting new HLS player: {self._state.stream_url}"
                )
                self.command = FFMPEG_COMMAND.format(
                    self._state.stream_url, self.filename
                )

                time.sleep(3)
                self._log.info(f"Debug Player start: {self.name}")
                self.start_ffmpeg()
        elif not self.check_process():
            self._log.info(
                f"ffmpeg process is not active, removing ffmpeg process"
            )
            self.cleanup()
        else:
            # read errors must be ran to prevent deadlock
            self.read_errors()

    def _invalid_stream_loop(self):
        if self.process is None:
            if self._sxm_running and self._state.stream_url is None:
                now = time.time()
                if now > self._event_cooldown:
                    self._event_cooldown = now + 10
                    self._log.info(
                        f"Starting new HLS stream: {self.channel_id}"
                    )
                    self.push_event(
                        EventMessage(
                            self.name,
                            EventMessage.TRIGGER_HLS_STREAM,
                            (self.channel_id, self.stream_protocol),
                        )
                    )
        else:
            self._log.info(f"stream is dead, killing ffmpeg")
            self.cleanup()

    def cleanup(self):
        self.stop_ffmpeg()
        self._state.stream_data = (None, None)

    def _handle_event(self, event: EventMessage):
        if event.msg_type == EventMessage.SXM_RUNNING_EVENT:
            self._sxm_running = True
        elif event.msg_type == EventMessage.SXM_STOPPED_EVENT:
            self._sxm_running = False
        elif event.msg_type == EventMessage.HLS_STREAM_STARTED:
            self._state.stream_data = event.msg
        elif event.msg_type == EventMessage.UPDATE_METADATA_EVENT:
            self._state.set_raw_live(event.msg)
        elif event.msg_type == EventMessage.UPDATE_CHANNELS_EVENT:
            self._state.channels = event.msg
        elif event.msg_type == EventMessage.KILL_HLS_STREAM:
            self._log.info(f"stream is stopping, killing ffmpeg")
            self.cleanup()
        else:
            self._log.warning(
                f"Unknown event received: {event.msg_src}, {event.msg_type}"
            )
