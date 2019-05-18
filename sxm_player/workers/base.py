import logging
import time
from multiprocessing import Event as MPEvent
from typing import List, Optional, Tuple

from ..models import PlayerState
from ..queue import Event, EventMessage, Queue
from ..signals import (
    default_signal_handler,
    init_signals,
    interupt_signal_handler,
)

__all__ = [
    "BaseWorker",
    "InterruptableWorker",
    "LoopedWorker",
    "SXMStatusSubscriber",
    "HLSStatusSubscriber",
    "SXMLoopedWorker",
]


class BaseWorker:
    NAME = "worker"

    _log: logging.Logger

    name: str = NAME
    int_handler: staticmethod = staticmethod(default_signal_handler)
    term_handler: staticmethod = staticmethod(default_signal_handler)
    startup_event: MPEvent  # type: ignore
    shutdown_event: MPEvent  # type: ignore
    local_shutdown_event: MPEvent  # type: ignore

    def __init__(
        self,
        startup_event: MPEvent,  # type: ignore
        shutdown_event: MPEvent,  # type: ignore
        local_shutdown_event: MPEvent,  # type: ignore
        event_queue: Queue,
        name: str = "worker",
        *args,
        **kwargs,
    ):
        self._log = logging.getLogger(f"sxm_player.{name}")

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
                            f"{event.msg_type.name}"
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
    _state: PlayerState

    def __init__(self, sxm_status: bool, *args, **kwargs):
        sxm_status_queue = kwargs.pop("sxm_status_queue")
        SXMStatusSubscriber.__init__(self, sxm_status_queue)
        super().__init__(*args, **kwargs)

        self._state = PlayerState()
        self._state.sxm_running = sxm_status
        self._event_queues = [self.sxm_status_queue]

    def _handle_event(self, event: EventMessage):
        if event.msg_type == Event.SXM_STATUS:
            self._state.sxm_running = event.msg
        else:
            self._log.warning(
                f"Unknown event received: {event.msg_src}, {event.msg_type}"
            )


class HLSLoopedWorker(EventedWorker, HLSStatusSubscriber):
    _state: PlayerState

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

        self._state = PlayerState()
        self._state.stream_data = stream_data
        self._state.channels = channels  # type: ignore
        self._state.set_raw_live(raw_live_data)

    def _handle_event(self, event: EventMessage):
        if event.msg_type == Event.HLS_STREAM_STARTED:
            self._state.stream_data = event.msg
        elif event.msg_type == Event.UPDATE_METADATA:
            self._state.set_raw_live(event.msg)
        elif event.msg_type == Event.UPDATE_CHANNELS:
            self._state.channels = event.msg
        elif event.msg_type == Event.KILL_HLS_STREAM:
            self.local_shutdown_event.set()  # type: ignore
        else:
            self._log.warning(
                f"Unknown event received: {event.msg_src}, {event.msg_type}"
            )


class ComboLoopedWorker(
    EventedWorker, SXMStatusSubscriber, HLSStatusSubscriber
):
    _state: PlayerState

    def __init__(
        self,
        sxm_status: bool,
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

        self._state = PlayerState()
        self._state.sxm_running = sxm_status
        self._state.stream_data = stream_data
        self._state.set_raw_live(raw_live_data)
