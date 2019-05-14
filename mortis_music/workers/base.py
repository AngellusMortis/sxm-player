import logging
from multiprocessing import Event
from typing import Tuple, Optional, List
import time
import select
import subprocess  # nosec
import shlex
import psutil

from ..signals import (
    default_signal_handler,
    init_signals,
    interupt_signal_handler,
)
from ..models import XMState
from ..queue import Queue, EventMessage

__all__ = [
    "BaseWorker",
    "InterruptableWorker",
    "LoopedWorker",
    "SXMStatusSubscriber",
    "HLSStatusSubscriber",
    "SXMLoopedWorker",
]


class BaseWorker:
    _log: logging.Logger

    name: str = "worker"
    int_handler: staticmethod = staticmethod(default_signal_handler)
    term_handler: staticmethod = staticmethod(default_signal_handler)
    startup_event: Event  # type: ignore
    shutdown_event: Event  # type: ignore
    local_shutdown_event: Event  # type: ignore

    def __init__(
        self,
        startup_event: Event,  # type: ignore
        shutdown_event: Event,  # type: ignore
        local_shutdown_event: Event,  # type: ignore
        event_queue: Queue,
        name: str = "worker",
        *args,
        **kwargs,
    ):
        self._log = logging.getLogger(f"mortis_music.{name}")

        self.name = name

        self.startup_event = startup_event
        self.shutdown_event = shutdown_event
        self.local_shutdown_event = local_shutdown_event
        self.event_queue = event_queue

    def init_signals(self):
        self._log.debug("Entering init_signals")
        signal_object = init_signals(
            self.shutdown_event, self.int_handler, self.term_handler
        )
        return signal_object

    def start(self):
        self.init_signals()

        self.startup_event.set()
        return self.run()

    def run(self):
        raise NotImplementedError("run method not implemented")

    def push_event(self, event: EventMessage):
        success = self.event_queue.safe_put(event)

        if not success:
            self._log.error(
                f"Could not pass event: {event.msg_src}, {event.msg_type}"
            )


class InterruptableWorker(BaseWorker):
    int_handler: staticmethod = staticmethod(interupt_signal_handler)
    term_handler: staticmethod = staticmethod(interupt_signal_handler)


class LoopedWorker(BaseWorker):
    _delay: float = 1

    def run(self):
        self.setup()

        while not self.shutdown_event.is_set():
            time.sleep(self._delay)
            self.loop()

        self.cleanup()

    def cleanup(self):
        pass

    def setup(self):
        pass

    def loop(self):
        raise NotImplementedError("loop method not implemented")


class SXMStatusSubscriber:
    sxm_status_queue: Queue

    def __init__(self, sxm_status_queue):
        self.sxm_status_queue = sxm_status_queue


class HLSStatusSubscriber:
    hls_stream_queue: Queue

    def __init__(self, hls_stream_queue):
        self.hls_stream_queue = hls_stream_queue


class EventedWorker(LoopedWorker):
    _last_loop: float = 0
    _event_queues: List[Queue]
    _event_delay: float = 0

    def run(self):
        self.setup()

        try:
            while (
                not self.shutdown_event.is_set()
                and not self.local_shutdown_event.is_set()
            ):
                for queue in self._event_queues:
                    event = queue.safe_get()

                    if event:
                        self._log.debug(
                            f"Received event: {event.msg_src}, "
                            f"{event.msg_type}"
                        )
                        self._handle_event(event)

                if time.time() > (self._last_loop + self._delay):
                    self.loop()
                    self._last_loop = time.time()
        except Exception as e:
            self._log.error(f"Exception occurred in {self.name}: {e}")

        self.cleanup()

    def _handle_event(self, event: EventMessage):
        raise NotImplementedError("_handle_event method not implemented")


class SXMLoopedWorker(EventedWorker, SXMStatusSubscriber):
    _sxm_running: bool = False

    def __init__(self, *args, **kwargs):
        sxm_status_queue = kwargs.pop("sxm_status_queue")
        SXMStatusSubscriber.__init__(self, sxm_status_queue)
        super().__init__(*args, **kwargs)

        self._event_queues = [self.sxm_status_queue]

    def _handle_event(self, event: EventMessage):
        if event.msg_type == EventMessage.SXM_RUNNING_EVENT:
            self._sxm_running = True
        elif event.msg_type == EventMessage.SXM_STOPPED_EVENT:
            self._sxm_running = False
        else:
            self._log.warning(
                f"Unknown event received: {event.msg_src}, {event.msg_type}"
            )


class HLSLoopedWorker(EventedWorker, HLSStatusSubscriber):
    _state: XMState

    def __init__(
        self,
        stream_data: Tuple[Optional[str], Optional[str]] = (None, None),
        channels: Optional[List[dict]] = None,
        raw_live_data: Tuple[
            Optional[float], Optional[float], Optional[dict]
        ] = (None, None, None),
        *args,
        **kwargs,
    ):
        hls_stream_queue = kwargs.pop("hls_stream_queue")
        HLSStatusSubscriber.__init__(self, hls_stream_queue)
        super().__init__(*args, **kwargs)

        self._event_queues = [self.hls_stream_queue]

        self._state = XMState()
        self._state.stream_data = stream_data
        self._state.channels = channels  # type: ignore
        self._state.set_raw_live(raw_live_data)

    def _handle_event(self, event: EventMessage):
        if event.msg_type == EventMessage.HLS_STREAM_STARTED:
            self._state.stream_data = event.msg
        elif event.msg_type == EventMessage.UPDATE_METADATA_EVENT:
            self._state.set_raw_live(event.msg)
        elif event.msg_type == EventMessage.UPDATE_CHANNELS_EVENT:
            self._state.channels = event.msg
        elif event.msg_type == EventMessage.KILL_HLS_STREAM:
            self.local_shutdown_event.set()  # type: ignore
        else:
            self._log.warning(
                f"Unknown event received: {event.msg_src}, {event.msg_type}"
            )


class ComboLoopedWorker(
    EventedWorker, SXMStatusSubscriber, HLSStatusSubscriber
):
    _sxm_running: bool = False
    _state: XMState

    def __init__(
        self,
        stream_data: Tuple[Optional[str], Optional[str]],
        raw_live_data: Tuple[Optional[float], Optional[float], Optional[dict]],
        *args,
        **kwargs,
    ):
        sxm_status_queue = kwargs.pop("sxm_status_queue")
        SXMStatusSubscriber.__init__(self, sxm_status_queue)

        hls_stream_queue = kwargs.pop("hls_stream_queue")
        HLSStatusSubscriber.__init__(self, hls_stream_queue)
        super().__init__(*args, **kwargs)

        self._event_queues = [self.hls_stream_queue, self.sxm_status_queue]

        self._state = XMState()
        self._state.stream_data = stream_data
        self._state.set_raw_live(raw_live_data)


class FFmpegPlayer:
    ACTIVE_STATUS = [
        psutil.STATUS_RUNNING,
        psutil.STATUS_SLEEPING,
        psutil.STATUS_DISK_SLEEP,
    ]

    command: str
    process: Optional[subprocess.Popen] = None

    _stderr_poll: Optional[select.poll] = None  # pylint: disable=E1101

    def start_ffmpeg(self) -> None:
        ffmpeg_args = shlex.split(self.command)

        self.process = subprocess.Popen(  # nosec
            ffmpeg_args, stderr=subprocess.PIPE
        )

        self._stderr_poll = select.poll()  # pylint: disable=E1101
        self._stderr_poll.register(
            self.process.stderr, select.POLLIN  # pylint: disable=E1101 # noqa
        )

    def check_process(self) -> bool:
        if self.process is None:
            return False

        process = psutil.Process(self.process.pid)
        status = process.status()

        return status in FFmpegPlayer.ACTIVE_STATUS

    def stop_ffmpeg(self) -> None:
        if self.process is None:
            return

        self.process.kill()
        if self.process.poll() is None:
            self.process.communicate()

        self.process = None

    def read_errors(self) -> List[str]:
        if self.process is None or self._stderr_poll is None:
            return []

        lines: List[str] = []
        while self._stderr_poll.poll(0.1):
            lines.append(self.process.stderr.readline().decode("utf8"))

        return lines
