import logging
from typing import Type, Tuple, TypeVar, Dict, Optional, List
from multiprocessing import Process, Event
import time

from .signals import default_signal_handler, init_signals
from .utils import configure_root_logger
from .workers import BaseWorker, SXMStatusSubscriber, HLSStatusSubscriber
from .queue import Queue

STOP_WAIT_SECS = 3.0
STARTUP_WAIT_SECS = 10.0


def _sleep_secs(max_sleep, end_time=999_999_999_999_999.9):
    # Calculate time left to sleep, no less than 0
    return max(0.0, min(end_time - time.time(), max_sleep))


def worker_wrapper(
    worker_class: Type[BaseWorker],
    log_level: str,
    log_file: Optional[str],
    startup_event: Event,  # type: ignore
    shutdown_event: Event,  # type: ignore
    local_shutdown_event: Event,  # type: ignore
    event_queue: Queue,
    sxm_status_queue: Optional[Queue],
    hls_stream_queue: Optional[Queue],
    name: str,
    *args,
    **kwargs,
):

    kwargs["name"] = name
    kwargs["startup_event"] = startup_event
    kwargs["shutdown_event"] = shutdown_event
    kwargs["local_shutdown_event"] = local_shutdown_event
    kwargs["event_queue"] = event_queue

    if issubclass(worker_class, SXMStatusSubscriber):
        kwargs["sxm_status_queue"] = sxm_status_queue

    if issubclass(worker_class, HLSStatusSubscriber):
        kwargs["hls_stream_queue"] = hls_stream_queue

    configure_root_logger(log_level, log_file)

    worker = worker_class(*args, **kwargs)
    return worker.start()


class Worker:
    startup_event: Event  # type: ignore
    shutdown_event: Event  # type: ignore
    local_shutdown_event: Event  # type: ignore
    process: Process
    name: str
    sxm_status_queue: Optional[Queue] = None
    hls_stream_queue: Optional[Queue] = None

    def __init__(
        self,
        logger: logging.Logger,
        log_level: str,
        log_file: Optional[str],
        worker_class: Type[BaseWorker],
        shutdown_event: Event,  # type: ignore
        event_queue: Queue,
        sxm_status_queue: Optional[Queue],
        hls_stream_queue: Optional[Queue],
        name: str,
        debug: bool,
        *args,
        **kwargs,
    ):

        self.name = name
        self.log = logger
        self.startup_event = Event()
        self.shutdown_event = shutdown_event
        self.local_shutdown_event = Event()
        self.sxm_status_queue = sxm_status_queue
        self.hls_stream_queue = hls_stream_queue

        self.process = Process(
            target=worker_wrapper,
            args=(
                worker_class,
                log_level,
                log_file,
                self.startup_event,
                self.shutdown_event,
                self.local_shutdown_event,
                event_queue,
                sxm_status_queue,
                hls_stream_queue,
                name,
                *args,
            ),
            kwargs=kwargs,
        )

        self.log.debug(f"Starting worker: {name}")
        self.process.start()

        timeout = STARTUP_WAIT_SECS
        if debug:
            timeout = 999_999_999_999_999

        started = self.startup_event.wait(timeout=timeout)

        self.log.debug(f"Startup Event: {name} got {started}")
        if not started:
            self.terminate()
            raise RuntimeError(
                f"Process {name} failed to startup after {timeout} seconds"
            )

    def full_stop(self, wait_time=STOP_WAIT_SECS):
        self.log.debug(f"stopping: {self.name}")
        self.local_shutdown_event.set()
        self.process.join(wait_time)
        if self.process.is_alive():
            self.terminate()

    def terminate(self):
        self.log.debug(f"Terminating: {self.name}")

        NUM_TRIES = 3
        tries = NUM_TRIES
        while tries and self.process.is_alive():
            self.process.terminate()
            time.sleep(0.01)
            tries -= 1

        if self.process.is_alive():
            self.log.error(
                f"Failed to terminate {self.name} after {NUM_TRIES} attempts"
            )
            return False
        else:
            self.log.info(
                f"Terminated {self.name} after {NUM_TRIES - tries} attempt(s)"
            )
            return True


RunnerType = TypeVar("RunnerType", bound="Runner")


class Runner:
    workers: Dict[str, Worker]
    queues: List[Queue]
    shutdown_event: Event  # type: ignore
    event_queue: Queue
    log: logging.Logger
    log_level: str
    log_file: Optional[str]

    def __init__(self, log_file: Optional[str], debug: bool):
        self.workers = {}
        self.queues = []
        self.shutdown_event = Event()
        self.event_queue = self.create_queue()

        log_level = "INFO"
        if debug:
            log_level = "DEBUG"

        configure_root_logger(log_level, log_file)
        self.log = logging.getLogger("sxm_player")
        self.log_level = log_level
        self.log_file = log_file

    def __enter__(self: RunnerType) -> RunnerType:
        init_signals(
            self.shutdown_event, default_signal_handler, default_signal_handler
        )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.log.error(
                f"Exception: {exc_val}", exc_info=(exc_type, exc_val, exc_tb)
            )

        self.stop_workers()
        self.stop_queues()

        # -- Don't eat exceptions that reach here.
        return not exc_type

    def stop_workers(self) -> Tuple[int, int]:
        self.shutdown_event.set()  # type: ignore
        end_time = time.time() + STOP_WAIT_SECS
        num_terminated = 0
        num_failed = 0

        # Gracefully let the process try to stop
        for worker in self.workers.values():
            join_secs = _sleep_secs(STOP_WAIT_SECS, end_time)
            worker.process.join(join_secs)

        still_running: Dict[str, Worker] = {}
        while len(self.workers.keys()) > 0:
            first_key = list(self.workers.keys())[0]
            worker = self.workers.pop(first_key)
            terminated, failed, running = self.stop_worker(worker)

            num_terminated += terminated
            num_failed += failed
            if running:
                still_running[worker.name] = worker

        self.workers = still_running
        return num_failed, num_terminated

    def stop_worker(self, worker) -> Tuple[int, int, bool]:
        terminated = 0
        failed = 0
        running = False

        if worker.process.is_alive():
            if worker.terminate():
                terminated = 1
            else:
                running = True
        else:
            exitcode = worker.process.exitcode
            if exitcode:
                self.log.error(
                    (
                        f"Process {worker.name} ended with "
                        f"exitcode {exitcode}"
                    )
                )
                terminated = 2
            else:
                self.log.debug(f"Process {worker.name} stopped successfully")

        return (terminated, failed, running)

    def stop_queues(self) -> int:
        num_items_left = 0
        # -- Clear the queues list and close all associated queues
        for q in self.queues:
            num_items_left += sum(1 for __ in q.drain())
            q.close()

        # -- Wait for all queue threads to stop
        while self.queues:
            q = self.queues.pop(0)
            q.join_thread()
        return num_items_left

    def create_queue(self, *args, **kwargs) -> Queue:
        queue = Queue(*args, **kwargs)
        self.queues.append(queue)

        return queue

    def create_worker(
        self, worker_class: Type[BaseWorker], name: str, *args, **kwargs
    ) -> Worker:

        sxm_status_queue: Optional[Queue] = None
        hls_stream_queue: Optional[Queue] = None
        if issubclass(worker_class, SXMStatusSubscriber):
            sxm_status_queue = self.create_queue()

        if issubclass(worker_class, HLSStatusSubscriber):
            hls_stream_queue = self.create_queue()

        worker = Worker(
            self.log,
            self.log_level,
            self.log_file,
            worker_class,
            self.shutdown_event,
            self.event_queue,
            sxm_status_queue,
            hls_stream_queue,
            name,
            self.log_level == "DEBUG",
            *args,
            **kwargs,
        )
        self.workers[name] = worker
        return worker
