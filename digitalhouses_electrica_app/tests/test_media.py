"""Media player capabilities, browser and shared dispatch."""
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from threading import RLock
from unittest.mock import Mock
from electrica import media_rules as mr
from electrica.catalog import CatalogError
from electrica.control import light_commands
from electrica.event_log import EventLog
from electrica.ha_registry import HARegistryClient
from electrica.ingress import browse_media, validate_assignment
from electrica.ingress_catalog import target_catalog
from electrica.light_rules import parse_rule
from test_ingress import REGISTRIES, STATES, PROFILE
import test_ha_native_output as native
from test_lab_rest_fallback import NAME, BASE, LAB

E="media_player.livingroom"
FLAGS=sum(mr.FEATURES.values())|mr.BROWSE
REF={"media_content_id":"media-source://radio_browser/station","media_content_type":"music","title":"Radio"}

def state(status="playing",vol=.25,flags=FLAGS):
    return {"entity_id":E,"state":status,"attributes":{"supported_features":flags,"volume_level":vol,"friendly_name":"Колонка зала"}}

def assignment(op,data=None):
    return {"entity_id":E,"operation":op,"data":data or {}}

def rule(op,data=None):
    return parse_rule({"assignments":[assignment(op,data)]})

class MediaTests(unittest.TestCase):
    def test_catalog_and_strict_parameters(self):
        regs=deepcopy(REGISTRIES)
        regs[2].append({"entity_id":E,"device_id":"target"})
        cat=target_catalog(regs,STATES+[state()],PROFILE)
        self.assertEqual(set(cat[E]["operations"]),set(mr.SERVICES))
        self.assertEqual(cat[E]["volume_pct"],25)
        self.assertEqual(mr.capabilities({"supported_features":512})["operations"],[])
        self.assertEqual(mr.capabilities({"supported_features":1})["operations"],["pause"])
        validate_assignment(assignment("play_media",REF),cat)
        for op,data in [("volume",{"volume_pct":101}),("volume",{"volume_pct":True}),("volume",{"volume_pct":20.5}),
                        ("play_media",{"media_content_id":"x"}),("play",{"url":"x"}),("off",{})]:
            with self.assertRaises(CatalogError):rule(op,data)
        cmd=light_commands({"fingerprint":{"actions":["single"]},"bindings":{"single":rule("volume",{"volume_pct":30})}},"single")
        self.assertEqual(cmd,[{"service":"media_player.volume_set","target":{"entity_id":[E]},"data":{"volume_pct":30}}])

    def test_toggle_volume_and_media_planning(self):
        self.assertEqual(mr.plan("play_pause",{},state()),("pause",{},"paused"))
        self.assertEqual(mr.plan("play_pause",{},state("paused")),("play",{},"playing"))
        self.assertEqual(mr.plan("volume",{"volume_pct":35},state("idle")),("volume",{"volume_level":.35},"volume:35"))
        self.assertEqual(mr.plan("play_media",REF,state()),("play_media",{k:v for k,v in REF.items() if k!="title"},None))
        for status in ("off","standby","unknown","unavailable"):
            with self.assertRaises(CatalogError):mr.plan("volume",{"volume_pct":35},state(status))
        for op in ("next","previous","stop"):
            self.assertEqual(mr.plan(op,{},state()),(op,{},None))

    def test_worker_dispatch_never_adds_play_for_volume(self):
        for status,expected in [("idle",True),("off",False),("unavailable",False)]:
            app,ha,_=native.NativeLightIntegration().build([LAB],registry=[{"entity_id":E,"platform":"mqtt"}])
            app.config["rooms"][0]["switches"][0]["bindings"]["double"]=rule("volume",{"volume_pct":40})
            ha.read_domain_state.return_value=state(status)
            results,_=native.NativeLightIntegration().run_button(app)
            if expected:
                self.assertEqual(results[0]["state"],"sent")
                ha.execute_media.assert_called_once_with(E,"volume",{"volume_level":.4})
            else:
                self.assertEqual(results[0]["state"],"skipped")
                ha.execute_media.assert_not_called()

    def test_media_browse_uses_read_only_ws_and_filters_items(self):
        client=HARegistryClient("test")
        item={**REF,"can_play":True,"can_expand":False,"thumbnail":"secret"}
        client._fetch=Mock(return_value=[{"children":[item,{}]}])
        app=SimpleNamespace(_mutex=RLock(),target_catalog={E:{"operations":["play_media"]}},registry=client)
        result=browse_media(app,{"entity_id":E})
        self.assertEqual(result["children"],[{**REF,"can_play":True,"can_expand":False}])
        client._fetch.assert_called_once_with(({"type":"media_player/browse_media","entity_id":E},))
        with self.assertRaises(CatalogError):browse_media(app,{"entity_id":"media_player.missing"})
        browse_media(app,{"entity_id":E,"ref":REF})
        self.assertEqual(client._fetch.call_args.args[0][0]["media_content_id"],REF["media_content_id"])

    def test_log_volume_confirmation_and_accepted_track_command(self):
        log=EventLog()
        now=datetime.now(timezone.utc)
        rid=log.press(BASE,NAME,"double",[E])
        log.sent_ha_domain(rid,E,state(),"volume:40",now.isoformat(),operation="volume")
        for vol,seconds in ((.25,1),(.4,-1),(.4,1)):
            log.ha_observations([{**state(vol=vol),"last_updated":(now+timedelta(seconds=seconds)).isoformat()}])
            self.assertEqual(log.snapshot()["rows"][0]["targets"][E]["status"],"confirmed" if vol==.4 and seconds==1 else "sent")
        rid=log.press(BASE,NAME,"double",[E])
        log.sent_ha_domain(rid,E,state(),None,now.isoformat(),operation="next")
        target=log.snapshot()["rows"][-1]["targets"][E]
        self.assertEqual((target["status"],target["desired"]),("accepted","next"))
