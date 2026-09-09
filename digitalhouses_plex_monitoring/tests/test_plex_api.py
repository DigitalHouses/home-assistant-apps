import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.plex_api import (
    LibraryInfo,
    PlexApiCollector,
    PlaybackSession,
    build_plex_api_payload,
    parse_sessions_xml,
    playback_fingerprint,
    resolve_token_path,
)


DIRECT_PLAY_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<MediaContainer size="2">
  <Video title="Аватар: Пламя и пепел" type="movie" year="2025" sessionKey="9">
    <Media audioChannels="6" audioCodec="ac3" bitrate="5268" container="mkv" videoCodec="av1" videoResolution="1080" selected="1">
      <Part container="mkv" decision="directplay" selected="1">
        <Stream streamType="1" codec="av1" bitrate="4820" displayTitle="1080p (AV1)" location="direct" />
        <Stream streamType="2" codec="ac3" channels="6" bitrate="448" selected="1" location="direct" />
      </Part>
    </Media>
    <User title="Beybars" />
    <Player device="iPhone" platform="iOS" state="playing" title="iPhone" playbackId="fallback" playbackSessionId="video-session" />
    <Session bandwidth="8298" location="lan" />
  </Video>
  <Track title="This Waiting Heart" type="track" parentTitle="Spark to a Flame: The Very Best of Chris de Burgh" parentYear="1989" grandparentTitle="Chris de Burgh" sessionKey="10">
    <Media audioChannels="2" audioCodec="flac" bitrate="924" container="flac" selected="1">
      <Part container="flac" decision="directplay" selected="1">
        <Stream streamType="2" bitDepth="16" bitrate="924" channels="2" codec="flac" samplingRate="44100" selected="1" location="direct" />
      </Part>
    </Media>
    <User title="Beybars" />
    <Player device="Windows" platform="Chrome" state="playing" title="Chrome" playbackSessionId="audio-session" />
    <Session bandwidth="985" location="lan" />
  </Track>
</MediaContainer>'''

TRANSCODE_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<MediaContainer size="1">
  <Video title="Люди Икс: Последняя битва" type="movie" year="2006" sessionKey="7">
    <Media audioCodec="aac" bitrate="20256" container="mp4" videoCodec="hevc" videoResolution="1080p" selected="1">
      <Part container="mp4" decision="transcode" selected="1">
        <Stream streamType="1" codec="hevc" decision="transcode" />
        <Stream streamType="2" codec="aac" decision="transcode" />
        <Stream streamType="3" codec="ass" decision="burn" selected="1" />
      </Part>
    </Media>
    <User title="Beybars" />
    <Player device="Windows" platform="Chrome" state="playing" title="Chrome" playbackSessionId="transcode-session" />
    <Session bandwidth="21269" location="lan" />
    <TranscodeSession videoDecision="transcode" audioDecision="transcode" subtitleDecision="burn" transcodeHwDecoding="vaapi" transcodeHwEncoding="vaapi" transcodeHwDecodingTitle="Intel (VA API)" transcodeHwEncodingTitle="Intel (VA API)" transcodeHwFullPipeline="1" />
  </Video>
</MediaContainer>'''

SECTIONS_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<MediaContainer size="3">
  <Directory key="1" type="movie" title="Фильмы"><Location path="/mnt/truenas/data/plex/movies" /></Directory>
  <Directory key="2" type="show" title="Телепередачи"><Location path="/mnt/truenas/data/plex/tvshows" /></Directory>
  <Directory key="3" type="artist" title="Музыка"><Location path="/mnt/truenas/data/plex/music" /></Directory>
</MediaContainer>'''


class PlexApiTests(unittest.TestCase):
    def test_video_and_audio_content_type_are_explicit(self):
        sessions = parse_sessions_xml(DIRECT_PLAY_XML)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].content_type, "video")
        self.assertEqual(sessions[0].media_type, "movie")
        self.assertEqual(sessions[0].mode, "Direct Play")
        self.assertEqual(sessions[0].session_id, "video-session")
        self.assertEqual(sessions[1].content_type, "audio")
        self.assertEqual(sessions[1].media_type, "track")
        self.assertEqual(sessions[1].mode, "Direct Play")
        self.assertEqual(sessions[1].artist, "Chris de Burgh")
        self.assertEqual(
            sessions[1].album,
            "Spark to a Flame: The Very Best of Chris de Burgh",
        )
        self.assertEqual(sessions[1].audio_codec, "flac")
        self.assertEqual(sessions[1].audio_channels, 2)
        self.assertEqual(sessions[1].bit_depth, 16)
        self.assertEqual(sessions[1].sample_rate_hz, 44100)

    def test_transcode_exposes_decisions_and_hardware(self):
        session = parse_sessions_xml(TRANSCODE_XML)[0]
        self.assertEqual(session.mode, "Transcode")
        self.assertEqual(session.video_decision, "transcode")
        self.assertEqual(session.audio_decision, "transcode")
        self.assertEqual(session.subtitle_decision, "burn")
        self.assertTrue(session.hardware_transcode)
        self.assertEqual(session.hw_decode, "Intel (VA API)")
        self.assertEqual(session.hw_encode, "Intel (VA API)")


    def test_video_copy_with_audio_transcode_is_direct_stream(self):
        xml = """<MediaContainer size="1">
          <Video title="Example" type="movie" sessionKey="11">
            <Media videoCodec="h264" audioCodec="ac3" selected="1">
              <Part decision="transcode" selected="1">
                <Stream streamType="1" codec="h264" decision="copy" />
                <Stream streamType="2" codec="aac" decision="transcode" selected="1" />
              </Part>
            </Media>
            <Player playbackSessionId="direct-stream-session" state="playing" />
            <TranscodeSession videoDecision="copy" audioDecision="transcode" />
          </Video>
        </MediaContainer>"""
        session = parse_sessions_xml(xml)[0]
        self.assertEqual(session.mode, "Direct Stream")

    def test_payload_counts_video_audio_and_sessions(self):
        sessions = parse_sessions_xml(DIRECT_PLAY_XML)
        libraries = (
            LibraryInfo("1", "Фильмы", "movie", "video", 15, "/movies", movies=15),
            LibraryInfo("3", "Музыка", "artist", "audio", 160, "/music", artists=3, albums=20, tracks=160),
        )
        payload = build_plex_api_payload(sessions, libraries, "ok")
        self.assertEqual(payload["playback_count"], 2)
        self.assertEqual(payload["video_playback_count"], 1)
        self.assertEqual(payload["audio_playback_count"], 1)
        self.assertTrue(payload["video_playback_active"])
        self.assertTrue(payload["audio_playback_active"])
        self.assertEqual(payload["library_count"], 2)
        self.assertEqual(payload["libraries_by_id"]["1"]["movies"], 15)
        self.assertEqual(payload["libraries_by_id"]["3"]["tracks"], 160)
        self.assertEqual(payload["playback_sessions"][0]["content_type"], "video")
        self.assertEqual(payload["playback_sessions"][1]["content_type"], "audio")

    def test_fingerprint_ignores_bandwidth_changes(self):
        first = parse_sessions_xml(DIRECT_PLAY_XML)
        changed = tuple(
            session if index else PlaybackSession(**{**session.__dict__, "bandwidth_kbps": 99999})
            for index, session in enumerate(first)
        )
        self.assertEqual(playback_fingerprint(first), playback_fingerprint(changed))

    def test_systemd_credential_is_preferred(self):
        with TemporaryDirectory() as tmp:
            credential = Path(tmp) / "plex_local_admin_token"
            credential.write_text("secret", encoding="utf-8")
            fallback = Path(tmp) / "fallback"
            with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": tmp}):
                self.assertEqual(resolve_token_path(fallback), credential)

    def test_libraries_have_real_counts_and_content_types(self):
        class FakeCollector(PlexApiCollector):
            def __init__(self):
                pass

            def _request_xml(self, path, *, query=None, count_only=False):
                import xml.etree.ElementTree as ET
                if path == "/library/sections":
                    return ET.fromstring(SECTIONS_XML), {}
                type_id = int((query or {}).get("type", 0))
                counts = {1: 15, 2: 2, 3: 6, 4: 60, 8: 3, 9: 20, 10: 160}
                return ET.fromstring('<MediaContainer size="0" totalSize="{}" />'.format(counts[type_id])), {}

        libraries = FakeCollector().collect_libraries()
        self.assertEqual(len(libraries), 3)
        self.assertEqual(libraries[0].content_type, "video")
        self.assertEqual(libraries[0].movies, 15)
        self.assertEqual(libraries[0].item_count, 15)
        self.assertEqual(libraries[1].shows, 2)
        self.assertEqual(libraries[1].seasons, 6)
        self.assertEqual(libraries[1].episodes, 60)
        self.assertEqual(libraries[1].item_count, 60)
        self.assertEqual(libraries[2].content_type, "audio")
        self.assertEqual(libraries[2].artists, 3)
        self.assertEqual(libraries[2].albums, 20)
        self.assertEqual(libraries[2].tracks, 160)
        self.assertEqual(libraries[2].item_count, 160)


if __name__ == "__main__":
    unittest.main()
