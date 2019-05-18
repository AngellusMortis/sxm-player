import os
from typing import Dict
import time

from sxm.models import XMMarker

from ..models import Episode, Song
from ..utils import get_air_time, get_files, splice_file
from .archiver import ARCHIVE_CHUNK
from .base import HLSLoopedWorker

__all__ = ["ProcessorWorker"]

MAX_DUPLICATE_COUNT = 3


class ProcessorWorker(HLSLoopedWorker):
    """ Runs song/show processor """

    NAME = "processor"

    _delay: float = ARCHIVE_CHUNK

    def __init__(
        self,
        processed_folder: str,
        archive_folder: str,
        reset_songs: bool,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.processed_folder = processed_folder
        self.archive_folder = archive_folder

        # run in 90 seconds and run ~30 seconds after Archiver
        self._last_loop = time.time() + 90 - ARCHIVE_CHUNK
        self._state.processed_folder = self.processed_folder
        self._state.db_reset = reset_songs

        os.makedirs(self.processed_folder, exist_ok=True)
        os.makedirs(self.archive_folder, exist_ok=True)

    def loop(self) -> None:
        self._delay = ARCHIVE_CHUNK

        if (
            self._state.stream_channel is None
            or self._state.live is None
            or self.archive_folder is None
        ):
            return None

        channel_archive = os.path.join(
            self.archive_folder, self._state.stream_channel
        )
        os.makedirs(channel_archive, exist_ok=True)

        archives = {}
        archive_files = get_files(channel_archive)
        for archive_file in archive_files:
            file_parts = archive_file.split(".")
            archive_key = f"{file_parts[1]}.{file_parts[2]}"
            archives[archive_key] = os.path.join(channel_archive, archive_file)
        self._log.debug(f"found {len(archives.keys())}")

        processed_songs = self._process_cuts(archives, is_song=True)

        processed_shows = self._process_cuts(archives, is_song=False)

        self._log.info(
            f"processed: {processed_songs} songs, {processed_shows} shows"
        )

    def _path_filter(self, word: str) -> str:
        """ Filters out known words to call issues for creating
        names for folders/files """

        return (
            word.replace("Counterfeit.", "Counterfeit")
            .replace("F**ker", "Fucker")
            .replace("Trust?", "Trust")
            .replace("P.O.D.", "POD")
            .replace("//", "-")
            .replace("@", "")
            .replace("(", "")
            .replace(")", "")
            .strip()
        )

    def _process_cut(
        self, archives: Dict[str, str], cut: XMMarker, is_song: bool = True
    ) -> bool:
        """ Processes `archives` to splice out an
            instance of `XMMarker` if it exists """

        if (
            self.processed_folder is None
            or self._state.stream_channel is None
            or self._state.db is None
        ):
            return False

        archive = None
        start = int(cut.time / 1000) + 20
        padded_duration = int(cut.duration + 20)
        end = start + padded_duration

        for archive_key, archive_file in archives.items():
            archive_start, archive_end = [
                int(i) for i in archive_key.split(".")
            ]

            if archive_start < start and archive_end > end:
                archive = archive_file
                start = start - archive_start
                end = start + padded_duration
                break

        if archive is not None:
            self._log.debug(f"found archive {archive}")

            title = None
            album_or_show = None
            artist = None
            filename = None
            folder = os.path.join(
                self.processed_folder, self._state.stream_channel
            )

            air_time = get_air_time(cut)

            if is_song:
                title = self._path_filter(cut.cut.title)
                artist = self._path_filter(cut.cut.artists[0].name)

                if (
                    cut.cut.album is not None
                    and cut.cut.album.title is not None
                ):
                    album_or_show = self._path_filter(cut.cut.album.title)

                filename = f"{title}.{cut.guid}.mp3"
                folder = os.path.join(folder, "songs", artist)
            else:
                title = self._path_filter(
                    cut.episode.long_title or cut.episode.medium_title
                )

                if cut.episode.show is not None:
                    album_or_show = self._path_filter(
                        cut.episode.show.long_title
                        or cut.episode.show.medium_title
                    )

                filename = (
                    f'{title}.{air_time.strftime("%Y-%m-%d-%H.%M")}'
                    f".{cut.guid}.mp3"
                )
                folder = os.path.join(folder, "shows")

            if album_or_show is not None:
                folder = os.path.join(folder, album_or_show)

            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, filename)
            self._log.debug(f"{cut.duration}: {path}")
            path = splice_file(archive, path, start, end)  # type: ignore

            if path is not None:
                if os.path.getsize(path) < 1000:
                    self._log.error(
                        f"spliced file too small, deleting {path}: {archive}"
                    )
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
                        channel=self._state.stream_channel,
                        file_path=path,
                    )
                else:
                    db_item = Episode(
                        guid=cut.guid,
                        title=title,
                        show=album_or_show,
                        air_time=air_time,
                        channel=self._state.stream_channel,
                        file_path=path,
                    )

                self._state.db.add(db_item)
                self._state.db.commit()
                self._log.debug(f"inserted cut {is_song}: {db_item.guid}")
                return True
        return False

    def _process_cuts(
        self, archives: Dict[str, str], is_song: bool = True
    ) -> int:
        """ Processes `archives` to splice out any
            instance of `XMMarker` if it exists """

        if self._state.live is None or self._state.db is None:
            return 0

        if is_song:
            cuts = self._state.live.song_cuts
        else:
            cuts = self._state.live.episode_markers

        processed = 0
        for cut in cuts:
            if cut.duration == 0.0:
                continue

            db_item = None
            if is_song:
                existing = (
                    self._state.db.query(Song)
                    .filter_by(
                        title=cut.cut.title, artist=cut.cut.artists[0].name
                    )
                    .all()
                )

                if len(existing) >= MAX_DUPLICATE_COUNT:
                    continue

                db_item = (
                    self._state.db.query(Song).filter_by(guid=cut.guid).first()
                )
            else:
                db_item = (
                    self._state.db.query(Episode)
                    .filter_by(guid=cut.guid)
                    .first()
                )

            if db_item is not None:
                continue

            title = None
            if is_song:
                title = cut.cut.title
            else:
                title = cut.episode.long_title or cut.episode.medium_title

            self._log.debug(
                f"processing {title}: "
                f"{cut.time}: {cut.duration}"
                f"{cut.guid}"
            )
            success = self._process_cut(archives, cut, is_song)

            if success:
                processed += 1
        return processed
