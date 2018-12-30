import logging
import os
import time
import traceback
from typing import List

from sxm.models import XMMarker

from .models import Episode, Song, XMState
from .utils import get_air_time, get_files, splice_file

__all__ = ['run_processor']

logger = logging.getLogger('discord_siriusxm.processor')

MAX_DUPLICATE_COUNT = 3


def path_filter(word: str) -> str:
    """ Filters out known words to call issues for creating
    names for folders/files """

    return word\
        .replace('Counterfeit.', 'Counterfeit')\
        .replace('F**ker', 'Fucker')\
        .replace('Trust?', 'Trust')\
        .replace('P.O.D.', 'POD')\
        .replace('//', '-')\
        .strip()


def process_cut(archives: List[str], state: XMState,
                cut: XMMarker, is_song: bool = True) -> bool:
    """ Processes `archives` to splice out an
        instance of `XMMarker` if it exists """

    archive = None
    start = int(cut.time / 1000) + 20
    padded_duration = int(cut.duration + 20)
    end = start + padded_duration

    for archive_key, archive_file in archives.items():
        archive_start, archive_end = archive_key.split('.')
        archive_start, archive_end = int(archive_start), int(archive_end)

        if archive_start < start and archive_end > end:
            archive = archive_file
            start = start - archive_start
            end = start + padded_duration
            break

    if archive is not None:
        logger.debug(f'found archive {archive}')

        title = None
        album_or_show = None
        artist = None
        filename = None
        folder = os.path.join(
            state.processed_folder, state.active_channel_id)

        air_time = get_air_time(cut)

        if is_song:
            title = path_filter(cut.cut.title)
            artist = path_filter(cut.cut.artists[0].name)

            if cut.cut.album is not None and cut.cut.album.title is not None:
                album_or_show = path_filter(cut.cut.album.title)

            filename = f'{title}.{cut.guid}.mp3'
            folder = os.path.join(folder, 'songs', artist)
        else:
            title = path_filter(cut.episode.long_title or
                                cut.episode.medium_title)

            if cut.episode.show is not None:
                album_or_show = path_filter(cut.episode.show.long_title or
                                            cut.episode.show.medium_title)

            filename = \
                f'{title}.{air_time.strftime("%Y-%m-%d-%H.%M")}.{cut.guid}.mp3'
            folder = os.path.join(folder, 'shows')

        if album_or_show is not None:
            folder = os.path.join(folder, album_or_show)

        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, filename)
        logger.debug(f'{cut.duration}: {path}')
        path = splice_file(archive, path, start, end)

        if path is not None:
            if os.path.getsize(path) < 1000:
                logger.error(
                    f'spliced file too small, deleting {path}: {archive}')
                os.remove(path)
                return False

            db_item = None

            if is_song:
                db_item = Song(
                    guid=cut.guid,
                    title=title,
                    artist=artist,
                    album=album_or_show,
                    air_time=air_time,
                    channel=state.active_channel_id,
                    file_path=path
                )
            else:
                db_item = Episode(
                    guid=cut.guid,
                    title=title,
                    show=album_or_show,
                    air_time=air_time,
                    channel=state.active_channel_id,
                    file_path=path
                )

            state.db.add(db_item)
            state.db.commit()
            logger.debug(f'inserted cut {is_song}: {db_item.guid}')
            return True
    return False


def process_cuts(archives: List[str], state: XMState,
                 is_song: bool = True) -> int:
    """ Processes `archives` to splice out any
        instance of `XMMarker` if it exists """

    if is_song:
        cuts = state.live.song_cuts
    else:
        cuts = state.live.episode_markers

    processed = 0
    for cut in cuts:
        if cut.duration == 0.0:
            continue

        db_item = None
        if is_song:
            existing = state.db.query(Song).filter_by(
                title=cut.cut.title,
                artist=cut.cut.artists[0].name
            ).all()

            if len(existing) >= MAX_DUPLICATE_COUNT:
                continue

            db_item = state.db.query(Song).filter_by(guid=cut.guid).first()
        else:
            db_item = state.db.query(Episode).filter_by(guid=cut.guid).first()

        if db_item is not None:
            continue

        title = None
        if is_song:
            title = cut.cut.title
        else:
            title = cut.episode.long_title or \
                cut.episode.medium_title

        logger.debug(
            f'processing {title}: '
            f'{cut.time}: {cut.duration}'
            f'{cut.guid}'
        )
        success = process_cut(archives, state, cut, is_song)

        if success:
            processed += 1
    return processed


def run_processor(state_dict: dict, reset_songs: bool) -> None:
    """ Runs song/show processor look """

    state = XMState(state_dict, db_reset=reset_songs)

    os.makedirs(state.processed_folder, exist_ok=True)
    os.makedirs(state.archive_folder, exist_ok=True)

    logger.info(f'processor started: {state.output}')
    sleep_time = 10
    while True:
        time.sleep(sleep_time)
        sleep_time = 600

        try:
            active_channel_id = state.active_channel_id

            if active_channel_id is None or \
                    state.live is None:
                continue

            channel_archive = os.path.join(
                state.archive_folder, state.active_channel_id)

            archives = {}
            archive_files = get_files(channel_archive)
            for archive_file in archive_files:
                file_parts = archive_file.split('.')
                archive_key = f'{file_parts[1]}.{file_parts[2]}'
                archives[archive_key] = os.path.join(
                    channel_archive, archive_file)
            logger.debug(f'found {len(archives.keys())}')

            processed_songs = process_cuts(archives, state, is_song=True)

            processed_shows = process_cuts(archives, state, is_song=False)

            logger.info(
                f'processed: {processed_songs} songs, {processed_shows} shows')
        except Exception as e:
            logger.error('error occuring in processor loop:')
            logger.error(traceback.format_exc())
            raise e
