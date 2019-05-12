import subprocess  # nosec
import shlex
from typing import Optional, Tuple
import os
import time
import psutil

from .base import InterruptableWorker, ComboLoopedWorker
from .hls import ACTIVE_STATUS

from ..queue import EventMessage

__all__ = ["DebugWorker", "DebugHLSPlayer"]

FFMPEG_COMMAND = "ffmpeg -y -loglevel fatal -f s16le -ar 48000 -ac 2 -i {} {}"
SAMPLING_RATE = 48000
FRAME_LENGTH = 20
SAMPLE_SIZE = 4  # (bit_rate / 8) * CHANNELS (bit_rate == 16)
SAMPLES_PER_FRAME = int(SAMPLING_RATE / 1000 * FRAME_LENGTH)
FRAME_SIZE = SAMPLES_PER_FRAME * SAMPLE_SIZE
DELAY = FRAME_LENGTH / 1000.0


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

    def kill_hls(self):
        self.push_event(
            EventMessage(self.name, EventMessage.KILL_HLS_STREAM, None)
        )


class DebugHLSPlayer(ComboLoopedWorker):
    channel_id: Optional[str]
    stream_protocol: str

    _process: Optional[subprocess.Popen]
    _event_cooldown: float = 0
    _loops: int = 0
    _start: float = 0

    def __init__(
        self,
        filename: str,
        *args,
        stream_protocol: str = "udp",
        stream_data: Tuple[Optional[str], Optional[str]] = (None, None),
        raw_live_data: Tuple[
            Optional[float], Optional[float], Optional[dict]
        ] = (None, None, None),
        **kwargs,
    ):
        kwargs["stream_data"] = stream_data
        kwargs["raw_live_data"] = raw_live_data
        super().__init__(*args, **kwargs)

        self._sxm_running = True
        self._process = None

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
        if self._process is None:
            if self._state.stream_url is not None:
                self._log.info(
                    f"Starting new HLS player: {self._state.stream_url}"
                )
                args = shlex.split(
                    FFMPEG_COMMAND.format(
                        self._state.stream_url, self.filename
                    )
                )

                time.sleep(3)
                self._log.info(f"Debug Player start: {self.name}")
                self._process = subprocess.Popen(args)  # nosec
        else:
            process = psutil.Process(self._process.pid)
            status = process.status()
            if status not in ACTIVE_STATUS:
                self._log.info(
                    f"ffmpeg process is {status}, removing ffmpeg process"
                )
                self.cleanup()

    def _invalid_stream_loop(self):
        if self._process is None:
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
        if self._process is None:
            return

        self._log.debug(
            "Preparing to terminate ffmpeg process %s.", self._process.pid
        )
        self._process.kill()
        if self._process.poll() is None:
            self._log.debug(
                f"ffmpeg process {self._process.pid} has not terminated. "
                f"Waiting to terminate..."
            )
            self._process.communicate()
            self._log.debug(
                f"ffmpeg process {self._process.pid} should have terminated "
                f"with a return code of {self._process.returncode}."
            )
        else:
            self._log.debug(
                f"ffmpeg process {self._process.pid} successfully terminated "
                f"with return code of {self._process.returncode}."
            )

        self._process = None
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
        elif event.msg_type == EventMessage.KILL_HLS_STREAM:
            self._log.info(f"stream is stopping, killing ffmpeg")
            self.cleanup()
        else:
            self._log.warning(
                f"Unknown event received: {event.msg_src}, {event.msg_type}"
            )
