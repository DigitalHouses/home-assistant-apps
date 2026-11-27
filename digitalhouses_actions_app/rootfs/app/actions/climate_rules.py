"""Explicit climate commands, not a climate-control algorithm."""
from collections.abc import Mapping
from math import isfinite, isclose
from .catalog import CatalogError

SERVICES = {"toggle":"climate.toggle","on":"climate.turn_on","off":"climate.turn_off",
            "hvac_mode":"climate.set_hvac_mode","temperature":"climate.set_temperature"}
MODES = {"off","heat","cool","heat_cool","auto","dry","fan_only"}
UNITS = {"°C","°F"}
TARGET_TEMPERATURE, TARGET_TEMPERATURE_RANGE, TURN_OFF, TURN_ON = 1,2,128,256


def number(v):
    return type(v) in (int,float) and isfinite(v)


def modes(attrs):
    value = attrs.get("hvac_modes")
    return list(dict.fromkeys(v for v in value if isinstance(v,str) and v in MODES)) if isinstance(value,list) else []


def capabilities(attrs, unit=None):
    flags=attrs.get("supported_features")
    flags=flags if type(flags) is int and flags>=0 else 0
    hvac=modes(attrs)
    ops=[]
    if "off" in hvac and any(v!="off" for v in hvac):
        if flags & TURN_ON and flags & TURN_OFF: ops.append("toggle")
        if flags & TURN_ON: ops.append("on")
    if "off" in hvac and flags & TURN_OFF: ops.append("off")
    if hvac: ops.append("hvac_mode")
    lo,hi,step=(attrs.get(k) for k in ("min_temp","max_temp","target_temp_step"))
    if flags & TARGET_TEMPERATURE and unit in UNITS and number(lo) and number(hi) and lo<=hi:
        ops.append("temperature")
    return {"operations":ops,"hvac_modes":hvac,"min_temp":lo if number(lo) else None,
            "max_temp":hi if number(hi) else None,"target_temp_step":step if number(step) and step>0 else None,
            "temperature_unit":unit if unit in UNITS else None,
            "temperature":attrs.get("temperature") if number(attrs.get("temperature")) else None}


def validate_data(operation,data):
    if operation not in SERVICES or not isinstance(data,Mapping):
        raise CatalogError("Unsupported climate operation")
    expected={"hvac_mode":{"hvac_mode"},"temperature":{"temperature","temperature_unit"}}.get(operation,set())
    if set(data)!=expected:
        raise CatalogError("Invalid climate parameters")
    if operation=="hvac_mode" and (not isinstance(data["hvac_mode"],str) or data["hvac_mode"] not in MODES):
        raise CatalogError("Invalid HVAC mode")
    if operation=="temperature" and (not number(data["temperature"]) or
            not isinstance(data["temperature_unit"],str) or data["temperature_unit"] not in UNITS):
        raise CatalogError("Invalid temperature or unit")
    return dict(data)


def validate_capability(operation,data,cap):
    validate_data(operation,data)
    if operation not in cap.get("operations",[]):
        raise CatalogError("Climate operation not supported")
    if operation=="hvac_mode" and data["hvac_mode"] not in cap["hvac_modes"]:
        raise CatalogError("HVAC mode not supported")
    if operation=="temperature":
        temp=data["temperature"]
        if (data["temperature_unit"]!=cap["temperature_unit"] or
                not cap["min_temp"]<=temp<=cap["max_temp"]):
            raise CatalogError("Temperature outside supported range or unit changed")
        step=cap.get("target_temp_step")
        if step and not isclose((temp-cap["min_temp"])/step,round((temp-cap["min_temp"])/step),rel_tol=0,abs_tol=1e-6):
            raise CatalogError("Temperature does not match supported step")


def plan(operation,data,state,unit=None):
    attrs=state.get("attributes",{})
    cap=capabilities(attrs,unit)
    current=state.get("state")
    if current not in cap["hvac_modes"]:
        raise CatalogError("Climate unavailable or HVAC mode unknown")
    validate_capability(operation,data,cap)
    if operation=="toggle":
        operation="on" if current=="off" else "off"
    if operation=="on":
        return operation,{},"active"
    if operation=="off":
        return operation,{},"off"
    if operation=="hvac_mode":
        return operation,data,data["hvac_mode"]
    if current=="heat_cool" and attrs["supported_features"] & TARGET_TEMPERATURE_RANGE:
        raise CatalogError("Active HVAC mode requires a temperature range")
    # No implicit mode change is included with the temperature request.
    return operation,{"temperature":data["temperature"]},"temperature:"+str(data["temperature"])


def observed_value(state,desired):
    current=state.get("state")
    if current not in MODES:
        return None
    if desired=="active":
        return desired if current!="off" else None
    if desired.startswith("temperature:"):
        temp=state.get("attributes",{}).get("temperature")
        return desired if number(temp) and isclose(temp,float(desired.split(":",1)[1]),rel_tol=0,abs_tol=1e-6) else None
    return current
