"""Compare a fresh reported light state with the command actually dispatched.

Z2M uses wire-level values (0..254, mired, XY or HS), avoiding conversion
round-trip errors. HA uses its reported active color mode and attributes.
Never treat a plain ON as a color/brightness confirmation.
"""
import math
from .mqtt_lights import _xy


def number(value):
    return type(value) in (float,int) and -1e9<=value<=1e9 and math.isfinite(value)


def near(value,expected,tolerance):
    return number(value) and number(expected) and abs(value-expected)<=tolerance


def xy_near(value,expected,tolerance=.01):
    return isinstance(value,dict) and all(near(value.get(k),expected.get(k),tolerance) for k in ("x","y"))


def rgb_xy(value):
    if (isinstance(value,(list,tuple)) and len(value)==3
            and all(number(x) and 0<=x<=255 for x in value) and any(value)):
        return _xy(*value)
    return None


def z2m_expected(payload):
    return {k:payload[k] for k in ("brightness","color_temp","color") if k in payload}


def ha_expected(data):
    return {k:data[k] for k in ("brightness_pct","color_temp_kelvin","rgb_color") if k in data}


def match_z2m(expected,report):
    if str(report.get("state","")).lower()!="on":
        return None
    actual={}
    if "brightness" in expected:
        if not near(report.get("brightness"),expected["brightness"],2):return None
        actual["brightness_pct"]=round(report["brightness"]*100/254)
    mode=report.get("color_mode")
    if "color_temp" in expected:
        if mode not in (None,"color_temp"):return None
        if mode is None and "color" in report:return None
        value=report.get("color_temp")
        if not near(value,expected["color_temp"],2) or value<=0:return None
        actual["color_temp_kelvin"]=round(1000000/value)
    if "color" in expected:
        color=report.get("color")
        target=expected["color"]
        if not isinstance(color,dict):return None
        if "x" in target:
            if mode not in (None,"xy") or (mode is None and "color_temp" in report):return None
            if not xy_near(color,target):return None
            actual["xy_color"]=[color["x"],color["y"]]
        elif "hue" in target:
            if mode not in (None,"hs","hue_saturation") or (mode is None and "color_temp" in report):return None
            hue,sat=color.get("hue"),color.get("saturation")
            if not number(hue) or not near(sat,target["saturation"],2):return None
            if target["saturation"]>2 and abs((hue-target["hue"]+180)%360-180)>2:return None
            actual["hs_color"]=[hue,sat]
        else:return None
    return actual or None


def match_ha(expected,state):
    if state.get("state")!="on":return None
    attrs=state.get("attributes",{})
    if not isinstance(attrs,dict):return None
    actual={}
    if "brightness_pct" in expected:
        value=attrs.get("brightness")
        if not number(value) or not near(value/255*100,expected["brightness_pct"],1):return None
        actual["brightness_pct"]=round(value/255*100)
    mode=attrs.get("color_mode")
    if "color_temp_kelvin" in expected:
        if mode!="color_temp" or not near(attrs.get("color_temp_kelvin"),expected["color_temp_kelvin"],50):return None
        actual["color_temp_kelvin"]=attrs["color_temp_kelvin"]
    if "rgb_color" in expected:
        if mode not in ("rgb","rgbw","rgbww","hs","xy"):return None
        target=rgb_xy(expected["rgb_color"])
        value=attrs.get("rgb_color")
        observed=rgb_xy(value)
        if target is None or observed is None or not xy_near(observed,target,.015):return None
        actual["rgb_color"]=list(value)
    return actual or None
