"""Run PVWatts v8 for PV arrays at one location.

Input weather is the JSON body weather-serve returns for
/v1/weather/point?format=json with variables T, GHI, DHI, DNI and WS_10M:
{"index": [UTC timestamps], "variables": {name: [values]}}.
"""

from dataclasses import dataclass
from datetime import datetime
from itertools import groupby

import PySAM.Pvwattsv8 as pvwatts

WEATHER_VARIABLES = ("T", "DHI", "DNI", "WS_10M")
IRRADIANCE_VARIABLES = ("DHI", "DNI")
MAX_ARRAYS = 50

MODULE_TYPES = {"standard": 0, "premium": 1, "thin_film": 2}
# PVWatts array_type: 0 fixed open rack, 1 fixed roof mount.
MOUNTINGS = {"open_rack": 0, "roof": 1}

ARRAY_DEFAULTS = {
    "capacity_kw": 1.0,
    "losses": 0.14,
    "dc_ac_ratio": 1.1,
    "inverter_efficiency": 0.96,
    "module_type": "standard",
    "mounting": "roof",
}


class RequestError(ValueError):
    """A request the service cannot run; retrying it unchanged fails again."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class Weather:
    """Hourly weather at one point, with gaps already filled."""

    stamps: list[datetime]
    values: dict[str, list[float]]
    filled: int


@dataclass(frozen=True)
class Array:
    """One PV array: a roof or wall surface with its module and inverter."""

    id: str
    capacity_kw: float
    tilt: float
    azimuth: float
    losses: float
    dc_ac_ratio: float
    inverter_efficiency: float
    module_type: str
    mounting: str


def parse_weather(body: object) -> Weather:
    """Validate weather-serve JSON and fill null values.

    Null irradiance becomes 0; null temperature or wind takes the nearest
    earlier value, or the first valid one at the start of the series.
    """
    if not isinstance(body, dict) or not isinstance(body.get("index"), list):
        raise RequestError("invalid_weather", "weather must be an object with an index list")
    variables = body.get("variables")
    if not isinstance(variables, dict):
        raise RequestError("invalid_weather", "weather.variables must be an object")
    missing = [name for name in WEATHER_VARIABLES if name not in variables]
    if missing:
        raise RequestError(
            "invalid_weather",
            f"weather.variables lacks {', '.join(missing)}",
            {"missing": missing},
        )
    index = body["index"]
    if not index:
        raise RequestError("invalid_weather", "weather.index is empty")
    stamps = [_parse_stamp(i, s) for i, s in enumerate(index)]
    values = {}
    filled = 0
    for name in WEATHER_VARIABLES:
        series = variables[name]
        if not isinstance(series, list) or len(series) != len(index):
            raise RequestError(
                "invalid_weather",
                f"weather.variables.{name} must be a list of {len(index)} values",
                {"variable": name},
            )
        values[name], n = _fill(name, series)
        filled += n
    return Weather(stamps=stamps, values=values, filled=filled)


def _parse_stamp(position: int, stamp: object) -> datetime:
    try:
        return datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise RequestError(
            "invalid_weather",
            f"weather.index[{position}] is {stamp!r}, expected YYYY-MM-DDTHH:MM:SSZ",
            {"position": position},
        ) from None


def _fill(name: str, series: list) -> tuple[list[float], int]:
    for position, value in enumerate(series):
        if value is not None and not isinstance(value, (int, float)):
            raise RequestError(
                "invalid_weather",
                f"weather.variables.{name}[{position}] is {value!r}, expected a number or null",
                {"variable": name, "position": position},
            )
    nulls = sum(value is None for value in series)
    if name in IRRADIANCE_VARIABLES:
        return [0.0 if v is None else float(v) for v in series], nulls
    valid = [v for v in series if v is not None]
    if not valid:
        raise RequestError(
            "invalid_weather", f"weather.variables.{name} has no values", {"variable": name}
        )
    out = []
    last = float(valid[0])
    for v in series:
        last = last if v is None else float(v)
        out.append(last)
    return out, nulls


def parse_arrays(body: object) -> list[Array]:
    """Validate the arrays list, applying defaults to omitted fields."""
    if not isinstance(body, list) or not body:
        raise RequestError("invalid_arrays", "arrays must be a non-empty list")
    if len(body) > MAX_ARRAYS:
        raise RequestError(
            "too_many_arrays",
            f"{len(body)} arrays in one request, at most {MAX_ARRAYS}",
            {"count": len(body), "max": MAX_ARRAYS},
        )
    arrays = [_parse_array(i, item) for i, item in enumerate(body)]
    ids = [a.id for a in arrays]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise RequestError(
            "invalid_arrays", f"duplicate array ids: {', '.join(duplicates)}", {"ids": duplicates}
        )
    return arrays


def _parse_array(position: int, item: object) -> Array:
    if not isinstance(item, dict):
        raise RequestError("invalid_arrays", f"arrays[{position}] must be an object")
    fields = {**ARRAY_DEFAULTS, **item}
    array_id = fields.get("id")
    if not isinstance(array_id, str) or not array_id:
        raise RequestError("invalid_arrays", f"arrays[{position}].id must be a non-empty string")
    where = f"arrays[{position}] ({array_id})"
    number = lambda key, lo, hi: _number(where, key, fields.get(key), lo, hi)  # noqa: E731
    module_type = fields["module_type"]
    if module_type not in MODULE_TYPES:
        raise RequestError(
            "invalid_arrays",
            f"{where}.module_type is {module_type!r}, expected one of {', '.join(MODULE_TYPES)}",
        )
    mounting = fields["mounting"]
    if mounting not in MOUNTINGS:
        raise RequestError(
            "invalid_arrays",
            f"{where}.mounting is {mounting!r}, expected one of {', '.join(MOUNTINGS)}",
        )
    return Array(
        id=array_id,
        capacity_kw=number("capacity_kw", 0.001, 100_000),
        tilt=number("tilt", 0, 90),
        azimuth=number("azimuth", 0, 360),
        losses=number("losses", 0, 0.99),
        dc_ac_ratio=number("dc_ac_ratio", 0.5, 2.0),
        inverter_efficiency=number("inverter_efficiency", 0.9, 0.995),
        module_type=module_type,
        mounting=mounting,
    )


def _number(where: str, key: str, value: object, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestError("invalid_arrays", f"{where}.{key} is {value!r}, expected a number")
    if not lo <= value <= hi:
        raise RequestError(
            "invalid_arrays", f"{where}.{key} is {value}, expected between {lo} and {hi}"
        )
    return float(value)


def simulate(lat: float, lon: float, elevation_m: float, weather: Weather, array: Array) -> list[float]:
    """Return the array's AC output in kW for every weather timestamp."""
    ac_kw: list[float] = []
    # PVWatts drops one day of a leap-year series (8784 hours in, 8760 out), so
    # each calendar year runs without 29 February and that day runs on its own.
    for _, group in groupby(range(len(weather.stamps)), key=lambda i: _run_key(weather.stamps[i])):
        positions = list(group)
        ac_kw.extend(_run(lat, lon, elevation_m, weather, array, positions))
    return ac_kw


def _run_key(stamp: datetime) -> tuple[int, bool]:
    return stamp.year, (stamp.month, stamp.day) == (2, 29)


def _run(
    lat: float, lon: float, elevation_m: float, weather: Weather, array: Array, positions: list[int]
) -> list[float]:
    stamps = [weather.stamps[i] for i in positions]
    pick = lambda name: [weather.values[name][i] for i in positions]  # noqa: E731
    model = pvwatts.new()
    model.SolarResource.solar_resource_data = {
        "lat": lat,
        "lon": lon,
        "tz": 0,
        "elev": elevation_m,
        "year": [s.year for s in stamps],
        "month": [s.month for s in stamps],
        "day": [s.day for s in stamps],
        "hour": [s.hour for s in stamps],
        "minute": [s.minute for s in stamps],
        "dn": pick("DNI"),
        "df": pick("DHI"),
        "tdry": pick("T"),
        "wspd": pick("WS_10M"),
    }
    design = model.SystemDesign
    design.system_capacity = array.capacity_kw
    design.tilt = array.tilt
    design.azimuth = array.azimuth
    design.array_type = MOUNTINGS[array.mounting]
    design.module_type = MODULE_TYPES[array.module_type]
    design.dc_ac_ratio = array.dc_ac_ratio
    design.inv_eff = array.inverter_efficiency * 100
    design.losses = array.losses * 100
    model.execute()
    ac_w = model.Outputs.ac
    if len(ac_w) != len(positions):
        raise RuntimeError(
            f"PVWatts returned {len(ac_w)} values for {len(positions)} hours of array {array.id}"
        )
    return [max(0.0, w / 1000) for w in ac_w]
