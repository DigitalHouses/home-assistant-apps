"""Capability-gated media player operations; no implicit playback for volume."""
from collections.abc import Mapping
from math import isclose
from .catalog import CatalogError
from .climate_rules import number

SERVICES={"play_pause":"media_player.media_play_pause","play":"media_player.media_play",
          "pause":"media_player.media_pause","stop":"media_player.media_stop",
          "next":"media_player.media_next_track","previous":"media_player.media_previous_track",
          "volume":"media_player.volume_set","play_media":"media_player.play_media"}
FEATURES={"play":16384,"pause":1,"stop":4096,"next":32,"previous":16,
          "volume":4,"play_media":512}
BROWSE=131072
STATES={"off","on","idle","playing","paused","buffering","standby"}

def capabilities(attrs):
    flags=attrs.get("supported_features")
    flags=flags if type(flags) is int and flags>=0 else 0
    ops=[op for op,bit in FEATURES.items() if flags & bit]
    if "play" in ops and "pause" in ops:ops.insert(0,"play_pause")
    # A selectable media source must be browsable by this entity.
    if "play_media" in ops and not flags & BROWSE:ops.remove("play_media")
    volume=attrs.get("volume_level")
    return {"operations":ops,"volume_pct":round(volume*100) if number(volume) and 0<=volume<=1 else None}

def media_ref(data):
    if not isinstance(data,Mapping):
        raise CatalogError("Invalid media reference")
    for key,limit in (("media_content_id",2048),("media_content_type",128)):
        value=data.get(key)
        if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(c)<32 for c in value):
            raise CatalogError("Invalid media reference")
    return {k:data[k] for k in ("media_content_id","media_content_type")}

def validate_data(op,data):
    if op not in SERVICES or not isinstance(data,Mapping):
        raise CatalogError("Unsupported media operation")
    if op=="volume":
        if set(data)!={"volume_pct"} or type(data["volume_pct"]) is not int or not 0<=data["volume_pct"]<=100:
            raise CatalogError("Volume must be 0..100%")
    elif op=="play_media":
        if set(data)!={"media_content_id","media_content_type","title"}:
            raise CatalogError("Select media from HA browser")
        media_ref(data)
        if not isinstance(data["title"],str) or not data["title"].strip() or len(data["title"])>512:
            raise CatalogError("Invalid media title")
    elif data:
        raise CatalogError("Unexpected media parameters")
    return dict(data)

def validate_capability(op,data,cap):
    validate_data(op,data)
    if op not in cap.get("operations",[]):
        raise CatalogError("Media operation not supported")

def plan(op,data,state):
    current=state.get("state")
    if current not in STATES:
        raise CatalogError("Media player unavailable")
    validate_capability(op,data,capabilities(state.get("attributes",{})))
    if op=="play_pause":
        if current in ("playing","buffering"):op="pause"
        elif current in ("paused","idle","on"):op="play"
        else:raise CatalogError("Play/Pause requires active player")
    if op=="volume":
        if current in ("off","standby"):
            raise CatalogError("Volume cannot wake player")
        return op,{"volume_level":data["volume_pct"]/100},"volume:"+str(data["volume_pct"])
    if op=="play_media":return op,media_ref(data),None
    return op,{},{"play":"playing","pause":"paused"}.get(op)

def observed_value(state,desired):
    if state.get("state") not in STATES:return None
    if desired.startswith("volume:"):
        v=state.get("attributes",{}).get("volume_level")
        return desired if number(v) and isclose(v*100,float(desired.split(":",1)[1]),rel_tol=0,abs_tol=0.5) else None
    return state.get("state")

def browse_result(result):
    """Expose only bounded browser metadata, not HA thumbnails or URLs for fetching."""
    def item(v):
        if not isinstance(v,dict):raise CatalogError("Invalid HA media item")
        ref=media_ref(v)
        title=v.get("title")
        if not isinstance(title,str) or not title.strip():raise CatalogError("Invalid HA media title")
        return {**ref,"title":title[:512],"can_play":v.get("can_play") is True,"can_expand":v.get("can_expand") is True}
    if not isinstance(result,dict):raise CatalogError("Invalid HA media browser")
    children=result.get("children") or []
    if not isinstance(children,list):raise CatalogError("Invalid HA media children")
    rows=[]
    for child in children[:500]:
        try:rows.append(item(child))
        except CatalogError:continue
    return {"children":rows,"truncated":len(children)>500}
