from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Mapping
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .config import PlexApiConfig


class PlexApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlaybackSession:
    session_id: str
    content_type: str
    media_type: str
    title: str
    year: int | None = None
    artist: str | None = None
    album: str | None = None
    album_year: int | None = None
    series: str | None = None
    season: int | None = None
    episode: int | None = None
    user: str | None = None
    player: str | None = None
    device: str | None = None
    platform: str | None = None
    state: str | None = None
    location: str | None = None
    bandwidth_kbps: int | None = None
    mode: str = "Unknown"
    video_decision: str | None = None
    audio_decision: str | None = None
    subtitle_decision: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    video_resolution: str | None = None
    audio_channels: int | None = None
    bit_depth: int | None = None
    sample_rate_hz: int | None = None
    media_bitrate_kbps: int | None = None
    hardware_transcode: bool = False
    hw_decode: str | None = None
    hw_encode: str | None = None


@dataclass(frozen=True)
class LibraryInfo:
    section_id: str
    title: str
    library_type: str
    content_type: str
    item_count: int
    path: str | None = None
    movies: int | None = None
    shows: int | None = None
    seasons: int | None = None
    episodes: int | None = None
    artists: int | None = None
    albums: int | None = None
    tracks: int | None = None


_LIBRARY_TYPE_IDS = {
    "movie": (("movies", 1),),
    "show": (("shows", 2), ("seasons", 3), ("episodes", 4)),
    "artist": (("artists", 8), ("albums", 9), ("tracks", 10)),
}


def _int_or_none(value: str | None) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _selected(parent: ET.Element | None, tag: str) -> ET.Element | None:
    if parent is None:
        return None
    children = parent.findall(tag)
    if not children:
        return None
    for child in children:
        if child.get("selected") == "1":
            return child
    return children[0]


def _stream(part: ET.Element | None, stream_type: str) -> ET.Element | None:
    if part is None:
        return None
    streams = [s for s in part.findall("Stream") if s.get("streamType") == stream_type]
    if not streams:
        return None
    for stream in streams:
        if stream.get("selected") == "1":
            return stream
    return streams[0]


def _decision(stream: ET.Element | None, *, direct_play: bool = False) -> str | None:
    if stream is None:
        return None
    value = stream.get("decision")
    if value:
        return value.casefold()
    if direct_play or stream.get("location") == "direct":
        return "direct"
    return None


def _mode(
    content_type: str,
    part_decision: str | None,
    transcode: ET.Element | None,
    video_decision: str | None,
    audio_decision: str | None,
    subtitle_decision: str | None,
) -> str:
    part = (part_decision or "").casefold()

    if part == "directplay":
        return "Direct Play"

    if content_type == "video":
        if video_decision == "transcode" or subtitle_decision == "burn":
            return "Transcode"
        if (
            transcode is not None
            or part in {"directstream", "direct_stream", "transcode"}
        ) and video_decision in {None, "copy", "direct"}:
            return "Direct Stream"

    if content_type == "audio":
        if audio_decision == "transcode" or part == "transcode":
            return "Transcode"
        if part in {"directstream", "direct_stream"}:
            return "Direct Stream"

    if video_decision == "transcode" or audio_decision == "transcode":
        return "Transcode"
    return "Unknown"


def parse_sessions_xml(xml_text: str | bytes) -> tuple[PlaybackSession, ...]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise PlexApiError(f"invalid Plex sessions XML: {exc}") from exc

    result: list[PlaybackSession] = []
    for item in root:
        if item.tag not in {"Video", "Track"}:
            continue

        content_type = "audio" if item.tag == "Track" else "video"
        media_type = item.get("type") or ("track" if content_type == "audio" else "video")
        media = _selected(item, "Media")
        part = _selected(media, "Part")
        video_stream = _stream(part, "1")
        audio_stream = _stream(part, "2")
        subtitle_stream = _stream(part, "3")
        transcode = item.find("TranscodeSession")
        player = item.find("Player")
        user = item.find("User")
        session = item.find("Session")

        direct_play = (part.get("decision") if part is not None else "") == "directplay"
        video_decision = (
            transcode.get("videoDecision").casefold()
            if transcode is not None and transcode.get("videoDecision")
            else _decision(video_stream, direct_play=direct_play)
        )
        audio_decision = (
            transcode.get("audioDecision").casefold()
            if transcode is not None and transcode.get("audioDecision")
            else _decision(audio_stream, direct_play=direct_play)
        )
        subtitle_decision = (
            transcode.get("subtitleDecision").casefold()
            if transcode is not None and transcode.get("subtitleDecision")
            else _decision(subtitle_stream, direct_play=direct_play)
        )

        hw_decode = None
        hw_encode = None
        hardware_transcode = False
        if transcode is not None:
            hw_decode = (
                transcode.get("transcodeHwDecodingTitle")
                or transcode.get("transcodeHwDecoding")
            )
            hw_encode = (
                transcode.get("transcodeHwEncodingTitle")
                or transcode.get("transcodeHwEncoding")
            )
            hardware_transcode = bool(
                transcode.get("transcodeHwFullPipeline") == "1"
                or transcode.get("transcodeHwDecoding")
                or transcode.get("transcodeHwEncoding")
            )

        playback_session_id = (
            player.get("playbackSessionId") if player is not None else None
        )
        playback_id = player.get("playbackId") if player is not None else None
        session_id = (
            playback_session_id
            or playback_id
            or item.get("sessionKey")
            or item.get("ratingKey")
            or "unknown"
        )

        result.append(
            PlaybackSession(
                session_id=session_id,
                content_type=content_type,
                media_type=media_type,
                title=item.get("title") or "Unknown",
                year=_int_or_none(item.get("year")),
                artist=item.get("grandparentTitle") if content_type == "audio" else None,
                album=item.get("parentTitle") if content_type == "audio" else None,
                album_year=(
                    _int_or_none(item.get("parentYear"))
                    if content_type == "audio"
                    else None
                ),
                series=item.get("grandparentTitle") if media_type == "episode" else None,
                season=(
                    _int_or_none(item.get("parentIndex"))
                    if media_type == "episode"
                    else None
                ),
                episode=(
                    _int_or_none(item.get("index"))
                    if media_type == "episode"
                    else None
                ),
                user=user.get("title") if user is not None else None,
                player=player.get("title") if player is not None else None,
                device=player.get("device") if player is not None else None,
                platform=player.get("platform") if player is not None else None,
                state=player.get("state") if player is not None else None,
                location=session.get("location") if session is not None else None,
                bandwidth_kbps=(
                    _int_or_none(session.get("bandwidth")) if session is not None else None
                ),
                mode=_mode(
                    content_type,
                    part.get("decision") if part is not None else None,
                    transcode,
                    video_decision,
                    audio_decision,
                    subtitle_decision,
                ),
                video_decision=video_decision,
                audio_decision=audio_decision,
                subtitle_decision=subtitle_decision,
                video_codec=(
                    video_stream.get("codec")
                    if video_stream is not None
                    else (media.get("videoCodec") if media is not None else None)
                ),
                audio_codec=(
                    audio_stream.get("codec")
                    if audio_stream is not None
                    else (media.get("audioCodec") if media is not None else None)
                ),
                video_resolution=(media.get("videoResolution") if media is not None else None),
                audio_channels=(
                    _int_or_none(audio_stream.get("channels"))
                    if audio_stream is not None
                    else (_int_or_none(media.get("audioChannels")) if media is not None else None)
                ),
                bit_depth=(
                    _int_or_none(audio_stream.get("bitDepth"))
                    if audio_stream is not None
                    else None
                ),
                sample_rate_hz=(
                    _int_or_none(audio_stream.get("samplingRate"))
                    if audio_stream is not None
                    else None
                ),
                media_bitrate_kbps=(
                    _int_or_none(media.get("bitrate")) if media is not None else None
                ),
                hardware_transcode=hardware_transcode,
                hw_decode=hw_decode,
                hw_encode=hw_encode,
            )
        )

    return tuple(result)


def _compact_dict(value: object) -> dict[str, object]:
    raw = asdict(value)
    return {key: item for key, item in raw.items() if item is not None}


def _playback_dict(session: PlaybackSession) -> dict[str, object]:
    payload = _compact_dict(session)
    payload.pop("session_id", None)
    return payload


def playback_fingerprint(sessions: tuple[PlaybackSession, ...]) -> tuple[tuple[object, ...], ...]:
    keys = []
    for s in sessions:
        keys.append(
            (
                s.session_id,
                s.content_type,
                s.media_type,
                s.title,
                s.year,
                s.artist,
                s.album,
                s.album_year,
                s.series,
                s.season,
                s.episode,
                s.user,
                s.player,
                s.device,
                s.platform,
                s.state,
                s.location,
                s.mode,
                s.video_decision,
                s.audio_decision,
                s.subtitle_decision,
                s.video_codec,
                s.audio_codec,
                s.video_resolution,
                s.hardware_transcode,
                s.hw_decode,
                s.hw_encode,
            )
        )
    return tuple(sorted(keys, key=lambda item: str(item[0])))


def library_fingerprint(libraries: tuple[LibraryInfo, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                library.section_id,
                library.title,
                library.library_type,
                library.content_type,
                library.item_count,
                library.path,
                library.movies,
                library.shows,
                library.seasons,
                library.episodes,
                library.artists,
                library.albums,
                library.tracks,
            )
            for library in libraries
        )
    )


def build_plex_api_payload(
    sessions: tuple[PlaybackSession, ...],
    libraries: tuple[LibraryInfo, ...],
    status: str,
) -> dict[str, object]:
    video_count = sum(1 for session in sessions if session.content_type == "video")
    audio_count = sum(1 for session in sessions if session.content_type == "audio")
    serialized_libraries = [_compact_dict(library) for library in libraries]
    return {
        "plex_api_status": status,
        "playback_count": len(sessions),
        "playback_sessions_state": (
            "1 session" if len(sessions) == 1 else f"{len(sessions)} sessions"
        ),
        "playback_active": bool(sessions),
        "video_playback_count": video_count,
        "audio_playback_count": audio_count,
        "video_playback_active": video_count > 0,
        "audio_playback_active": audio_count > 0,
        "playback_sessions": [_playback_dict(session) for session in sessions],
        "library_count": len(libraries),
        "libraries": serialized_libraries,
        "libraries_by_id": {
            library.section_id: _compact_dict(library) for library in libraries
        },
    }


def resolve_token_path(configured: Path) -> Path:
    credentials_dir = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    if credentials_dir:
        credential = Path(credentials_dir) / "plex_local_admin_token"
        if credential.is_file():
            return credential
    return configured


class PlexApiCollector:
    def __init__(self, config: PlexApiConfig) -> None:
        self.config = config

    def _read_token(self) -> str:
        path = resolve_token_path(self.config.token_file)
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PlexApiError(f"unable to read Plex LocalAdminToken {path}: {exc}") from exc
        if not token:
            raise PlexApiError(f"Plex LocalAdminToken is empty: {path}")
        return token

    def _request_xml(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        count_only: bool = False,
    ) -> tuple[ET.Element, Mapping[str, str]]:
        url = self.config.base_url.rstrip("/") + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {
            "X-Plex-Token": self._read_token(),
            "Accept": "application/xml",
        }
        if count_only:
            headers["X-Plex-Container-Start"] = "0"
            headers["X-Plex-Container-Size"] = "0"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.config.timeout_seconds,
            ) as response:
                body = response.read()
                response_headers = dict(response.headers.items())
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise PlexApiError(f"Plex API request failed for {path}: {exc}") from exc
        try:
            return ET.fromstring(body), response_headers
        except ET.ParseError as exc:
            raise PlexApiError(f"invalid Plex API XML for {path}: {exc}") from exc

    def collect_playback(self) -> tuple[PlaybackSession, ...]:
        root, _headers = self._request_xml("/status/sessions")
        return parse_sessions_xml(ET.tostring(root, encoding="unicode"))

    def _count_section(self, section_id: str, type_id: int) -> int:
        root, headers = self._request_xml(
            f"/library/sections/{urllib.parse.quote(section_id, safe='')}/all",
            query={"type": type_id},
            count_only=True,
        )
        for value in (
            root.get("totalSize"),
            headers.get("X-Plex-Container-Total-Size"),
            headers.get("x-plex-container-total-size"),
            root.get("size"),
        ):
            count = _int_or_none(value)
            if count is not None:
                return count
        return 0

    def collect_libraries(self) -> tuple[LibraryInfo, ...]:
        root, _headers = self._request_xml("/library/sections")
        libraries: list[LibraryInfo] = []
        for directory in root.findall("Directory"):
            section_id = directory.get("key") or ""
            library_type = directory.get("type") or "unknown"
            if not section_id or library_type not in _LIBRARY_TYPE_IDS:
                continue
            counts = {
                name: self._count_section(section_id, type_id)
                for name, type_id in _LIBRARY_TYPE_IDS[library_type]
            }
            content_type = "audio" if library_type == "artist" else "video"
            if library_type == "movie":
                item_count = counts["movies"]
            elif library_type == "show":
                item_count = counts["episodes"]
            else:
                item_count = counts["tracks"]
            location = directory.find("Location")
            libraries.append(
                LibraryInfo(
                    section_id=section_id,
                    title=directory.get("title") or f"Library {section_id}",
                    library_type=library_type,
                    content_type=content_type,
                    item_count=item_count,
                    path=location.get("path") if location is not None else None,
                    movies=counts.get("movies"),
                    shows=counts.get("shows"),
                    seasons=counts.get("seasons"),
                    episodes=counts.get("episodes"),
                    artists=counts.get("artists"),
                    albums=counts.get("albums"),
                    tracks=counts.get("tracks"),
                )
            )
        return tuple(libraries)
