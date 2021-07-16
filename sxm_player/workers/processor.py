import os
from datetime import timedelta
from time import monotonic
from typing import Dict, List, Optional, Union

from sxm.models import XMCutMarker, XMEpisodeMarker, XMSong

from sxm_player.models import DBEpisode, DBSong
from sxm_player.utils import (
    from_fs_datetime,
    get_art_thumb_url,
    get_art_url_by_size,
    get_files,
    splice_file,
)
from sxm_player.workers.archiver import ARCHIVE_CHUNK
from sxm_player.workers.base import HLSLoopedWorker

__all__ = ["ProcessorWorker"]

MAX_DUPLICATE_COUNT = 3
CUT_PADDING = timedelta(seconds=20)


class ProcessorWorker(HLSLoopedWorker):
    """Runs song/show processor"""

    NAME = "processor"

    _delay: float = ARCHIVE_CHUNK.total_seconds()

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
        self._last_loop = monotonic() + 90 - ARCHIVE_CHUNK.total_seconds()
        self._state.processed_folder = self.processed_folder
        self._state.db_reset = reset_songs

        # force db initialization
        self._state.db

        os.makedirs(self.processed_folder, exist_ok=True)
        os.makedirs(self.archive_folder, exist_ok=True)

    def loop(self) -> None:
        self._delay = ARCHIVE_CHUNK.total_seconds()

        if (
            self._state.stream_channel is None
            or self._state.live is None
            or self.archive_folder is None
        ):
            return None

        channel_archive = os.path.join(self.archive_folder, self._state.stream_channel)
        os.makedirs(channel_archive, exist_ok=True)

        archives = {}
        archive_files = get_files(channel_archive)
        for archive_file in archive_files:
            file_parts = archive_file.split(".")
            archive_key = f"{file_parts[1]}.{file_parts[2]}"
            archives[archive_key] = os.path.join(channel_archive, archive_file)
        self._log.debug(f"found {len(archives.keys())}")

        processed_songs = self._process_cuts(archives, self._state.live.song_cuts)
        processed_shows = self._process_cuts(archives, self._state.live.episode_markers)

        self._log.info(f"processed: {processed_songs} songs, {processed_shows} shows")

    def _path_filter(self, word: str) -> str:
        """Filters out known words to call issues for creating
        names for folders/files"""

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
        self, archives: Dict[str, str], cut: Union[XMCutMarker, XMEpisodeMarker]
    ) -> bool:
        """Processes `archives` to splice out an
        instance of `XMMarker` if it exists"""

        if (
            self.processed_folder is None
            or self._state.stream_channel is None
            or self._state.db is None
        ):
            return False

        archive = None
        start = cut.time + CUT_PADDING
        splice_start = timedelta(seconds=0)
        padded_duration = cut.duration + CUT_PADDING
        end = start + padded_duration
        splice_end = timedelta(seconds=0)

        for archive_key, archive_file in archives.items():
            archive_start, archive_end = [
                from_fs_datetime(i) for i in archive_key.split(".")
            ]

            if archive_start < start and archive_end > end:
                archive = archive_file
                splice_start = start - archive_start
                splice_end = splice_start + padded_duration
                break

        if archive is not None:
            self._log.debug(f"found archive {archive}")

            title = None
            album_or_show = None
            album_url = None
            artist = None
            filename = None
            folder = os.path.join(self.processed_folder, self._state.stream_channel)

            if isinstance(cut, XMEpisodeMarker):
                title = self._path_filter(
                    cut.episode.long_title or cut.episode.medium_title
                )

                if cut.episode.show is not None:
                    album_or_show = self._path_filter(
                        cut.episode.show.long_title or cut.episode.show.medium_title
                    )
                    album_url = get_art_thumb_url(cut.episode.show.arts)

                filename = (
                    f'{title}.{cut.time.strftime("%Y-%m-%d-%H.%M")}' f".{cut.guid}.mp3"
                )
                folder = os.path.join(folder, "shows")
            elif isinstance(cut.cut, XMSong):
                title = self._path_filter(cut.cut.title)
                artist = self._path_filter(cut.cut.artists[0].name)

                if cut.cut.album is not None and cut.cut.album.title is not None:
                    album_or_show = self._path_filter(cut.cut.album.title)
                    album_url = get_art_url_by_size(cut.cut.album.arts, "MEDIUM")

                filename = f"{title}.{cut.guid}.mp3"
                folder = os.path.join(folder, "songs", artist)
            else:
                return False

            if album_or_show is not None:
                folder = os.path.join(folder, album_or_show)

            os.makedirs(folder, exist_ok=True)
            path: Optional[str] = os.path.join(folder, filename)
            self._log.debug(f"{cut.duration}: {path}")
            if path is not None:
                self._log.debug(
                    f"Splice song: (Song: {start}, {end}, {cut.duration}), "
                    f"(Archive: {archive}, {splice_start}, {splice_end}"
                )
                path = splice_file(
                    archive,
                    path,
                    int(splice_start.total_seconds()),
                    int(splice_end.total_seconds()),
                )

            if path is not None:
                if os.path.getsize(path) < 1000:
                    self._log.error(
                        f"spliced file too small, deleting {path}: {archive}"
                    )
                    os.remove(path)
                    return False

                is_song = False
                if isinstance(cut, XMEpisodeMarker):
                    db_item: Union[DBSong, DBEpisode] = DBEpisode(
                        guid=cut.guid,
                        title=title,
                        show=album_or_show,
                        air_time=cut.time,
                        channel=self._state.stream_channel,
                        file_path=path,
                        image_url=album_url,
                    )
                elif isinstance(cut.cut, XMSong):
                    is_song = True
                    db_item = DBSong(
                        guid=cut.guid,
                        title=title,
                        artist=artist,
                        album=album_or_show,
                        air_time=cut.time,
                        channel=self._state.stream_channel,
                        file_path=path,
                        image_url=album_url,
                    )
                else:
                    return False

                self._state.db.add(db_item)
                self._state.db.commit()
                self._log.debug(f"inserted cut {is_song}: {db_item.guid}")
                return True
        return False

    def _process_cuts(
        self,
        archives: Dict[str, str],
        cuts: Union[List[XMCutMarker], List[XMEpisodeMarker]],
    ) -> int:
        """Processes `archives` to splice out any
        instance of `XMMarker` if it exists"""

        if self._state.live is None or self._state.db is None:
            return 0

        processed = 0
        for cut in cuts:
            if cut.duration == 0.0:
                continue

            db_item: Union[DBSong, DBEpisode, None] = None
            if isinstance(cut, XMEpisodeMarker):
                db_item = (
                    self._state.db.query(DBEpisode).filter_by(guid=cut.guid).first()
                )
            elif isinstance(cut.cut, XMSong):
                existing = (
                    self._state.db.query(DBSong)
                    .filter_by(title=cut.cut.title, artist=cut.cut.artists[0].name)
                    .all()
                )

                if len(existing) >= MAX_DUPLICATE_COUNT:
                    continue

                db_item = self._state.db.query(DBSong).filter_by(guid=cut.guid).first()

            if db_item is not None:
                continue

            title: Optional[str] = None
            if isinstance(cut, XMEpisodeMarker):
                title = cut.episode.long_title or cut.episode.medium_title
            elif isinstance(cut.cut, XMSong):
                title = cut.cut.title

            if title is None:
                title = "unknown"
            self._log.debug(
                f"processing {title}: " f"{cut.time}: {cut.duration}" f"{cut.guid}"
            )
            success = self._process_cut(archives, cut)

            if success:
                processed += 1
        return processed
