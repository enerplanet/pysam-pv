# PV production profiles

An HTTP service that returns hourly PV production profiles for one or more PV
arrays at a location. It runs NREL's PVWatts v8 (through NREL-PySAM) on the
hourly weather you send, in the format the weather service's point endpoint
returns. It holds no weather data of its own.

## Example

```bash
curl -s -X POST http://localhost:8080/v1/pv/simulate \
  -H 'Content-Type: application/json' \
  -d @- <<'EOF'
{
  "location": {"lat": 48.8295, "lon": 12.9554},
  "weather": {
    "index": ["2018-06-21T10:30:00Z", "2018-06-21T11:30:00Z"],
    "variables": {
      "T": [22.1, 23.4],
      "DHI": [180.0, 175.5],
      "DNI": [690.2, 720.8],
      "WS_10M": [2.1, 2.4]
    }
  },
  "arrays": [
    {"id": "roof_south", "capacity_kw": 6.0, "tilt": 35, "azimuth": 180},
    {"id": "roof_east", "tilt": 20, "azimuth": 90}
  ]
}
EOF
```

Response:

```json
{
  "index": ["2018-06-21T10:30:00Z", "2018-06-21T11:30:00Z"],
  "unit": "kW AC per kW DC",
  "filled_values": 0,
  "arrays": [
    {"id": "roof_south", "capacity_kw": 6.0, "energy_kwh": 8.09, "capacity_factor": [0.6651, 0.6833]},
    {"id": "roof_east", "capacity_kw": 1.0, "energy_kwh": 1.19, "capacity_factor": [0.6107, 0.5796]}
  ]
}
```

## Request

`POST /v1/pv/simulate`, JSON body, at most 16 MiB.

| Field | Required | Description |
|---|---|---|
| `location.lat`, `location.lon` | yes | WGS84 degrees |
| `location.elevation_m` | no | metres above sea level, default 0 |
| `weather` | yes | the JSON body of the weather service's `/v1/weather/point?format=json`, with variables `T` (°C), `DHI` and `DNI` (W/m²) and `WS_10M` (m/s); other variables are ignored |
| `arrays` | yes | 1 to 50 arrays, fields below |

Array fields:

| Field | Default | Range | Description |
|---|---|---|---|
| `id` | required | unique in the request | echoed in the response |
| `capacity_kw` | 1.0 | 0.001 to 100000 | DC nameplate capacity |
| `tilt` | required | 0 to 90 | degrees from horizontal |
| `azimuth` | required | 0 to 360 | degrees clockwise from north; 180 is south |
| `losses` | 0.14 | 0 to 0.99 | system losses as a fraction |
| `dc_ac_ratio` | 1.1 | 0.5 to 2.0 | |
| `inverter_efficiency` | 0.96 | 0.9 to 0.995 | fraction |
| `module_type` | `standard` | `standard`, `premium`, `thin_film` | |
| `mounting` | `roof` | `roof`, `open_rack` | fixed mounting |

Weather timestamps are UTC and may sit at any minute of the hour (MERRA-2 stamps
are at half past). The series may span several years and leap days.

A `null` irradiance value counts as 0. A `null` temperature or wind speed takes
the previous value, or the first valid one at the start. `filled_values` in
the response counts both.

## Response

| Field | Description |
|---|---|
| `index` | the weather timestamps, unchanged |
| `unit` | unit of `capacity_factor` |
| `filled_values` | number of `null` weather values filled |
| `arrays[].capacity_factor` | AC output per kW of DC capacity, one value per timestamp |
| `arrays[].energy_kwh` | AC energy over the whole series for the array's `capacity_kw` |

## Status codes

| Status | Cause | Retry |
|---|---|---|
| 200 | profiles computed | |
| 400 | body is not JSON, or a field is missing or out of range; `error.code` is one of `invalid_json`, `invalid_location`, `invalid_weather`, `invalid_arrays`, `too_many_arrays` | no, fix the request |
| 413 | body larger than 16 MiB (`request_too_large`) | no, send fewer years or arrays |
| 500 | simulation failed | once; report it if it repeats |

Errors have the body `{"error": {"code": "...", "message": "...", "details": {...}}}`;
`details` is present only when it has content.

`GET /health` returns `{"status": "ok"}`.

## Known limitations

- No snow loss, no shading and no albedo input: PVWatts runs with its default
  albedo of 0.2.
- MERRA-2 irradiance runs high in central Europe; a south-facing 35° array in
  Deggendorf yields about 1,300 kWh/kWp a year on 2018 weather.

## Run

```bash
docker compose up -d --build
```

The container is `pv-service` on port 8080 and joins the `tentacron-net`
network; from the host it answers on `localhost:8092` (`HOST_PORT`).
`WEB_CONCURRENCY` sets the number of worker processes (default 2).

Without Docker:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/gunicorn --bind 0.0.0.0:8080 'pv_service.app:create_app()'
```

## Licence and credits

See [LICENSE](LICENSE) and [ATTRIBUTIONS.md](ATTRIBUTIONS.md).
