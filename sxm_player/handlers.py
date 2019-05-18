import os
from typing import Optional

from .models import PlayerState
from .queue import Event, EventMessage
from .runner import Runner, Worker
from .workers import (
    ArchiveWorker,
    DebugHLSPlayer,
    HLSWorker,
    ProcessorWorker,
    ServerWorker,
)


def hls_start_event(runner: Runner, stream_data: tuple):
    hls_event(runner, Event.HLS_STREAM_STARTED, stream_data)


def hls_kill_event(runner: Runner):
    hls_event(runner, Event.KILL_HLS_STREAM, None)


def hls_metadata_event(runner: Runner, live_data: tuple):
    hls_event(runner, Event.UPDATE_METADATA, live_data)


def hls_channels_event(runner: Runner, channels: Optional[list]):
    hls_event(runner, Event.UPDATE_CHANNELS, channels)


def hls_event(runner: Runner, event: Event, data):
    for worker in runner.workers.values():
        if worker.hls_stream_queue is not None:
            push_event(
                runner,
                worker,
                "hls_stream_queue",
                EventMessage("main", event, data),
            )


def sxm_status_event(runner: Runner, event: Event, status: bool):
    for worker in runner.workers.values():
        if worker.sxm_status_queue is not None:
            push_event(
                runner,
                worker,
                "sxm_status_queue",
                EventMessage("main", event, status),
            )


def push_event(
    runner: Runner, worker: Worker, queue_name: str, event: EventMessage
):

    success = getattr(worker, queue_name).safe_put(event)

    if not success:
        runner.log.error(f"Could not pass status event to {worker.name}")


def handle_update_channels_event(
    event: EventMessage, runner: Runner, state: PlayerState, **kwargs
):
    state.channels = event.msg

    hls_channels_event(runner, state.get_raw_channels())


def handle_reset_sxm_event(
    event: EventMessage, runner: Runner, state: PlayerState, **kwargs
):

    sxm_worker = runner.workers.get(ServerWorker.NAME)
    if sxm_worker is not None:
        sxm_worker.terminate()
        state.channels = None  # type: ignore
        cooldown = state.increase_cooldown()

        runner.log.warning(
            "SiriusXM Client acting up, restarting it (cooldown: "
            f"{cooldown} seconds)"
        )

        del runner.workers[ServerWorker.NAME]

        state.sxm_running = False
        sxm_status_event(runner, Event.SXM_STATUS, state.sxm_running)


def handle_trigger_hls_stream_event(
    event: EventMessage,
    runner: Runner,
    state: PlayerState,
    host: str,
    port: int,
    output_folder: str,
    **kwargs,
):

    hls_worker = runner.workers.get(HLSWorker.NAME)
    stream_folder: Optional[str] = None
    if output_folder is not None:
        stream_folder = os.path.join(output_folder, "streams")

    if hls_worker is not None:
        src_worker = runner.workers.get(event.msg_src)
        if src_worker is not None and src_worker.hls_stream_queue is not None:
            push_event(
                runner,
                src_worker,
                "hls_stream_queue",
                EventMessage(
                    "main", Event.HLS_STREAM_STARTED, state.stream_data
                ),
            )
            runner.log.info(
                f"Could not start new {HLSWorker.NAME}, one is "
                "already running passing "
                f"{Event.HLS_STREAM_STARTED} instead"
            )
        else:
            runner.log.warning(
                f"Could not start new {HLSWorker.NAME}, one is "
                "already running and no request was not HLSPlayer"
            )
    elif state.get_channel(event.msg[0]) is not None:
        runner.create_worker(
            HLSWorker,
            HLSWorker.NAME,
            ip=host,
            port=port,
            channel_id=event.msg[0],
            stream_folder=stream_folder,
            stream_protocol=event.msg[1],
            sxm_status=state.sxm_running,
        )
        state.stream_channel = event.msg
    else:
        runner.log.warning(
            f"Could not start new {HLSWorker.NAME}, invalid "
            f"channel id: {event.msg}"
        )


def handle_kill_hls_stream_event(
    event: EventMessage, runner: Runner, state: PlayerState, **kwargs
):

    state.stream_data = (None, None)

    hls_worker = runner.workers.get(HLSWorker.NAME)
    hls_kill_event(runner)
    if hls_worker is not None:
        hls_worker.full_stop()

        runner.log.info(f"Terminated {HLSWorker.NAME} worker")

        del runner.workers[HLSWorker.NAME]


def handle_hls_stream_started_event(
    event: EventMessage,
    runner: Runner,
    state: PlayerState,
    output_folder: str,
    reset_songs: bool,
    **kwargs,
):

    stream_folder: Optional[str] = None
    archive_folder: Optional[str] = None
    processed_folder: Optional[str] = None
    if output_folder is not None:
        stream_folder = os.path.join(output_folder, "streams")
        archive_folder = os.path.join(output_folder, "archive")
        processed_folder = os.path.join(output_folder, "processed")

    state.stream_data = event.msg
    hls_start_event(runner, state.stream_data)

    if output_folder is not None:
        runner.create_worker(
            ArchiveWorker,
            ArchiveWorker.NAME,
            stream_folder=stream_folder,
            archive_folder=archive_folder,
            stream_data=state.stream_data,
            channels=state.get_raw_channels(),
            raw_live_data=state.get_raw_live(),
        )

        runner.create_worker(
            ProcessorWorker,
            ProcessorWorker.NAME,
            processed_folder=processed_folder,
            archive_folder=archive_folder,
            reset_songs=reset_songs,
            stream_data=state.stream_data,
            channels=state.get_raw_channels(),
            raw_live_data=state.get_raw_live(),
        )


def handle_update_metadata_event(
    event: EventMessage, runner: Runner, state: PlayerState, **kwargs
):

    state.stream_channel = event.msg["channelId"]
    state.live = event.msg
    hls_metadata_event(runner, state.get_raw_live())


def handle_hls_stderror_lines_event(
    event: EventMessage, runner: Runner, state: PlayerState, **kwargs
):
    do_reset = False
    for line in event.msg:
        runner.log.debug(f"ffmpeg STDERR: {line}")

        if "503" in line:
            do_reset = True

    if do_reset:
        handle_reset_sxm_event(event, runner, state)


if DebugHLSPlayer is not None:

    def handle_debug_start_player_event(
        event: EventMessage, runner: Runner, state: PlayerState, **kwargs
    ):

        player_name = event.msg[0]
        channel_id = event.msg[1]
        filename = event.msg[2]
        stream_protocol = event.msg[3]

        if (
            state.stream_channel is not None
            and channel_id not in state.stream_channel
        ):
            runner.log.warning(
                "Cannot start player, different HLS stream "
                f"playing: {state.stream_url}"
            )
        else:
            runner.create_worker(
                DebugHLSPlayer,
                player_name,
                filename=filename,
                stream_protocol=stream_protocol,
                sxm_status=state.sxm_running,
                stream_data=(channel_id, state.stream_url),
                channels=state.get_raw_channels(),
                raw_live_data=state.get_raw_live(),
            )

    def handle_debug_stop_player_event(
        event: EventMessage, runner: Runner, **kwargs
    ):

        worker = runner.workers.get(event.msg)
        if worker is None:
            runner.log.warning(
                f"Debug Player {event.msg} is not currently running"
            )
        else:
            worker.full_stop()
