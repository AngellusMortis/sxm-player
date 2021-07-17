import time
from typing import Optional

from ..queue import EventMessage, EventTypes
from ..utils import FFmpeg
from .base import ComboLoopedWorker

FFMPEG_COMMAND = "ffmpeg -y -loglevel fatal -f mpegts -i {} {}"


class CLIPlayerWorker(ComboLoopedWorker, FFmpeg):
    channel_id: Optional[str]
    stream_protocol: str

    _event_cooldown: float = 0

    def __init__(self, filename: str, *args, stream_protocol: str = "udp", **kwargs):
        super().__init__(*args, **kwargs)

        self.channel_id = self._state.stream_channel
        self.stream_protocol = stream_protocol
        self.filename = filename

        if self.channel_id is None:
            raise RuntimeError("No channel_id or stream_url provided")

    def loop(self):
        if self._state.sxm_running and self._state.stream_url is not None:
            self._valid_stream_loop()
        else:
            self._invalid_stream_loop()

    def _valid_stream_loop(self):
        if self.process is None:
            if self._state.stream_url is not None:
                self._log.info(f"Starting new HLS player: {self._state.stream_url}")
                self.command = FFMPEG_COMMAND.format(
                    self._state.stream_url, self.filename
                )

                time.sleep(3)
                self._log.info(f"CLI Player start: {self.name}")
                self.start_ffmpeg()
        elif not self.check_process():
            self._log.info("ffmpeg process is not active, removing ffmpeg process")
            self.cleanup()
        else:
            # read errors must be ran to prevent deadlock
            self.read_errors()

    def _invalid_stream_loop(self):
        if self.process is None:
            if self._state.sxm_running and self._state.stream_url is None:
                now = time.monotonic()
                if now > self._event_cooldown:
                    self._event_cooldown = now + 10
                    self._log.info(f"Starting new HLS stream: {self.channel_id}")
                    self.push_event(
                        EventMessage(
                            self.name,
                            EventTypes.TRIGGER_HLS_STREAM,
                            (self.channel_id, self.stream_protocol),
                        )
                    )
        else:
            self._log.info("stream is dead, killing ffmpeg")
            self.cleanup()

    def cleanup(self):
        self.stop_ffmpeg()
        self._state.update_stream_data((None, None))

    def _handle_event(self, event: EventMessage):
        if event.msg_type == EventTypes.SXM_STATUS:
            self._state.sxm_running = event.msg
        elif event.msg_type == EventTypes.HLS_STREAM_STARTED:
            self._state.update_stream_data(event.msg)
        elif event.msg_type == EventTypes.UPDATE_METADATA:
            self._state.set_raw_live(event.msg)
        elif event.msg_type == EventTypes.UPDATE_CHANNELS:
            self._state.update_channels(event.msg)
        elif event.msg_type == EventTypes.KILL_HLS_STREAM:
            self._log.info("stream is stopping, killing ffmpeg")
            self.cleanup()
        else:
            self._log.warning(
                f"Unknown event received: {event.msg_src}, {event.msg_type}"
            )
