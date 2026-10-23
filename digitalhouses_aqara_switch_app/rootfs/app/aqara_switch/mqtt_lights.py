"""MQTT-only smart-light executor planning.

Never use bare Z2M TOGGLE: infer a single ON/OFF for the whole action.
Skip offline, unknown, unverified and unconfirmed lamps; no queued replay.
"""
from __future__ import annotations
import colorsys
from collections.abc import Mapping
from .light_routes import current_route
from .actions import ActionError

SHADOW_SECONDS = 5.0

def _xy(red: int, green: int, blue: int) -> dict:
    def gamma(v):
        c = v / 255.0
        return ((c + 0.055) / 1.055)**2.4 if c > 0.04045 else c / 12.92
    r, g, b = map(gamma, (red, green, blue))
    x = r*0.664511 + g*0.154324 + b*0.162028
    y = r*0.283881 + g*0.668433 + b*0.047685
    z = r*0.000088 + g*0.072310 + b*0.986039
    total = x+y+z
    if total <= 0:
        raise ActionError("RGB [0,0,0] has no representable XY chromaticity")
    return {"x": round(x/total, 4), "y": round(y/total, 4)}

def _mqtt_data(data: Mapping, features: Mapping, observed: Mapping,
               state: str) -> dict:
    payload = {"state": state}
    if state == "OFF":
        if "transition" in data:
            payload["transition"] = data["transition"]
        return payload
    if "brightness_pct" in data or "brightness_step_pct" in data:
        if "brightness" not in features:
            raise ActionError("Z2M lamp does not expose writable brightness")
        if "brightness_step_pct" in data:
            current = observed.get("brightness")
            if type(current) not in (int, float) or not 0 <= current <= 254:
                raise ActionError("Brightness step requires observed current brightness")
            value = int(round(current + 254 * data["brightness_step_pct"]/100.0))
        else:
            value = int(round(data["brightness_pct"] * 254/100.0))
        lower=features["brightness"].get("value_min", 0)
        upper=features["brightness"].get("value_max", 254)
        payload["brightness"] = max(lower, min(upper, value))
    if "color_temp_kelvin" in data:
        if "color_temp" not in features:
            raise ActionError("Z2M lamp does not expose writable color_temp")
        mired = int(round(1_000_000/data["color_temp_kelvin"]))
        bounds = features["color_temp"]
        if (mired < bounds.get("value_min", 1) or
                mired > bounds.get("value_max", 1000)):
            raise ActionError("Color temperature outside Z2M lamp capability")
        payload["color_temp"] = mired
    if "rgb_color" in data:
        if "color_xy" in features:
            payload["color"] = _xy(*data["rgb_color"])
        elif "color_hs" in features:
            h,s,_ = colorsys.rgb_to_hsv(*(x/255 for x in data["rgb_color"]))
            payload["color"] = {"hue": round(360*h, 1),
                                "saturation": round(100*s, 1)}
        else:
            raise ActionError("Z2M lamp does not expose writable color")
    if "transition" in data:
        payload["transition"] = data["transition"]
    return payload

def plan_batch(commands: list[dict], routes: Mapping, networks: Mapping,
               availability: Mapping, fresh_fields: set, shadows: Mapping,
               observed_at: Mapping, now: float) -> tuple[list[dict],list[dict]]:
    """All targets share one toggle decision across available known lamps.

    A pending command shadows the previous observed state until acknowledged.
    After timeout, a missing fresh confirmation causes a safe skip instead
    of making a possibly wrong blind group-toggle decision.
    """
    selected, skipped = [], []
    seen = set()
    for command in commands:
        service = command.get("service")
        if service not in ("light.toggle", "light.turn_on", "light.turn_off"):
            raise ActionError("Only light services can be dispatched via MQTT")
        for entity in command.get("target", {}).get("entity_id", []):
            if entity in seen:
                raise ActionError("Duplicate target in MQTT light action")
            seen.add(entity)
            route = routes.get(entity)
            if not isinstance(route, Mapping):
                skipped.append({"light":entity,"reason":"No verified Z2M route; run Scan"})
                continue
            base, name = route.get("base_topic"), route.get("friendly_name")
            net = networks.get(base, {})
            ident=(base,name)
            if (not isinstance(base,str) or not isinstance(name,str) or
                    net.get("bridge_state") != "online" or
                    not current_route(route,net)):
                skipped.append({"light":entity,"reason":"Z2M bridge or hardware route unverified"})
                continue
            if availability.get(ident) != "online":
                skipped.append({"light":entity,"reason":"Z2M availability is offline or unknown"})
                continue
            observed=net.get("states",{}).get(name,{})
            if not isinstance(observed, Mapping):
                observed={}
            shadow=shadows.get(ident)
            state=observed.get("state")
            if shadow is not None:
                if now-shadow["at"] <= SHADOW_SECONDS:
                    state=shadow["value"]  # in-flight command takes priority
                elif observed_at.get(ident,-1) <= shadow["at"]:
                    state=None  # no fresh feedback: fail closed
            if service == "light.toggle":
                if ident not in fresh_fields and (base,name,"state") not in fresh_fields:
                    # Runtime carries a tuple-based fresh field set.
                    skipped.append({"light":entity,"reason":"No fresh Z2M state"})
                    continue
                if state not in ("ON","OFF"):
                    skipped.append({"light":entity,"reason":"Unknown/unconfirmed light state"})
                    continue
            selected.append({"light":entity,"route":route,"service":service,
                             "data":command.get("data",{}),"observed":observed,
                             "state":state,"ident":ident})
    # Group toggle: if any available/known lamp is OFF -> ON all,
    # otherwise OFF all. Never send individual TOGGLE payloads.
    toggles=[item for item in selected if item["service"]=="light.toggle"]
    toggle_state=("ON" if any(item["state"]=="OFF" for item in toggles)
                  else "OFF") if toggles else None
    plans=[]
    for item in selected:
        state=(toggle_state if item["service"]=="light.toggle"
               else "ON" if item["service"]=="light.turn_on" else "OFF")
        try:
            payload=_mqtt_data(item["data"],item["route"]["features"],
                               item["observed"],state)
        except ActionError as exc:
            skipped.append({"light":item["light"],"reason":str(exc)})
            continue
        plans.append({"light":item["light"],"ident":item["ident"],
                      "topic":item["route"]["base_topic"]+"/"+
                              item["route"]["friendly_name"]+"/set",
                      "payload":payload,"state":state})
    return plans, skipped
