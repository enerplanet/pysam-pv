"""Tests for pv_service against a year of real MERRA-2 weather at Deggendorf."""

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pv_service.app import create_app

WEATHER = json.loads((Path(__file__).parent / "data" / "merra2_2018_deggendorf.json").read_text())
LOCATION = {"lat": 48.8295, "lon": 12.9554}


@pytest.fixture
def client():
    return create_app().test_client()


def post(client, weather=WEATHER, arrays=None, location=LOCATION):
    arrays = arrays or [{"id": "roof", "tilt": 35, "azimuth": 180}]
    return client.post(
        "/v1/pv/simulate", json={"location": location, "weather": weather, "arrays": arrays}
    )


def by_id(response):
    return {a["id"]: a for a in response.get_json()["arrays"]}


def test_annual_yield_by_orientation(client):
    arrays = [
        {"id": "south", "tilt": 35, "azimuth": 180},
        {"id": "east", "tilt": 35, "azimuth": 90},
        {"id": "west", "tilt": 35, "azimuth": 270},
        {"id": "north", "tilt": 35, "azimuth": 0},
    ]
    response = post(client, arrays=arrays)
    assert response.status_code == 200
    energy = {k: a["energy_kwh"] for k, a in by_id(response).items()}
    # Bavarian rooftop yields are about 1000 to 1150 kWh/kWp; MERRA-2
    # irradiance runs high, so the bound is wider.
    assert 1000 < energy["south"] < 1500
    assert energy["south"] > energy["east"] > energy["north"]
    assert energy["south"] > energy["west"] > energy["north"]


def test_profile_aligns_with_weather(client):
    body = post(client).get_json()
    cf = body["arrays"][0]["capacity_factor"]
    assert body["index"] == WEATHER["index"]
    assert len(cf) == len(WEATHER["index"])
    assert all(0 <= v <= 1 for v in cf)
    dark = [i for i, ghi in enumerate(WEATHER["variables"]["GHI"]) if ghi == 0]
    assert dark and all(cf[i] == 0 for i in dark)


def test_capacity_scales_energy_not_profile(client):
    small, large = (
        by_id(post(client, arrays=[{"id": "a", "tilt": 30, "azimuth": 180, "capacity_kw": kw}]))["a"]
        for kw in (1, 5)
    )
    assert large["energy_kwh"] == pytest.approx(5 * small["energy_kwh"], rel=1e-6)
    assert large["capacity_factor"] == small["capacity_factor"]


def leap_year_weather(dark_feb29: bool) -> dict:
    """2018 weather restamped to 2020, with 28 February repeated as 29 February."""
    feb29 = 59 * 24
    start = datetime(2020, 1, 1, 0, 30)
    variables = {}
    for name, values in WEATHER["variables"].items():
        day = values[feb29 - 24 : feb29]
        if dark_feb29 and name in ("GHI", "DHI", "DNI"):
            day = [0.0] * 24
        variables[name] = values[:feb29] + day + values[feb29:]
    index = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ") for i in range(8784)]
    return {"index": index, "variables": variables}


def test_leap_year_keeps_every_hour_in_place(client):
    cf = post(client, weather=leap_year_weather(dark_feb29=True)).get_json()["arrays"][0][
        "capacity_factor"
    ]
    feb29 = 59 * 24
    assert len(cf) == 8784
    assert sum(cf[feb29 : feb29 + 24]) == 0
    assert sum(cf[feb29 - 24 : feb29]) > 0
    assert sum(cf[feb29 + 24 : feb29 + 48]) > 0


def test_two_years_in_one_request(client):
    second = [
        (datetime(2019, 1, 1, 0, 30) + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(8760)
    ]
    weather = {
        "index": WEATHER["index"] + second,
        "variables": {k: v + v for k, v in WEATHER["variables"].items()},
    }
    cf = post(client, weather=weather).get_json()["arrays"][0]["capacity_factor"]
    assert len(cf) == 17520


def test_null_values_are_filled_and_counted(client):
    weather = copy.deepcopy(WEATHER)
    noon = 180 * 24 + 11
    weather["variables"]["DNI"][noon] = None
    weather["variables"]["T"][0] = None
    weather["variables"]["WS_10M"][noon] = None
    response = post(client, weather=weather)
    assert response.status_code == 200
    assert response.get_json()["filled_values"] == 3


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda b: b["weather"]["variables"].pop("DNI"), "invalid_weather"),
        (lambda b: b["weather"]["variables"]["T"].pop(), "invalid_weather"),
        (lambda b: b["weather"]["index"].__setitem__(0, "2018-01-01 00:30"), "invalid_weather"),
        (lambda b: b["arrays"][0].update(tilt=95), "invalid_arrays"),
        (lambda b: b["arrays"][0].update(module_type="mono"), "invalid_arrays"),
        (lambda b: b["arrays"].append(dict(b["arrays"][0])), "invalid_arrays"),
        (lambda b: b.update(arrays=[{"id": f"a{i}", "tilt": 30, "azimuth": 180} for i in range(51)]), "too_many_arrays"),
        (lambda b: b["location"].pop("lat"), "invalid_location"),
    ],
)
def test_invalid_requests_are_400(client, change, code):
    body = {
        "location": dict(LOCATION),
        "weather": copy.deepcopy(WEATHER),
        "arrays": [{"id": "roof", "tilt": 35, "azimuth": 180}],
    }
    change(body)
    response = client.post("/v1/pv/simulate", json=body)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == code


def test_non_json_body_is_400(client):
    response = client.post("/v1/pv/simulate", data="nope", content_type="text/plain")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_json"


def test_health(client):
    assert client.get("/health").get_json() == {"status": "ok"}
