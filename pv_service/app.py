"""HTTP API: POST /v1/pv/simulate and GET /health."""

from flask import Flask, jsonify, request

from pv_service.simulate import RequestError, parse_arrays, parse_weather, simulate

# A year of hourly weather is about 0.5 MB as JSON; 16 MiB leaves room for
# several years plus a full arrays list.
MAX_REQUEST_BYTES = 16 * 1024 * 1024


def create_app() -> Flask:
    """Build the Flask app."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.post("/v1/pv/simulate")
    def pv_simulate():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _error(400, "invalid_json", "request body must be a JSON object")
        try:
            return jsonify(run_request(body))
        except RequestError as exc:
            return _error(400, exc.code, str(exc), exc.details)

    @app.errorhandler(413)
    def too_large(_exc):
        return _error(413, "request_too_large", f"request body exceeds {MAX_REQUEST_BYTES} bytes")

    return app


def run_request(body: dict) -> dict:
    """Validate a simulate request and return the response body."""
    lat, lon, elevation_m = _parse_location(body.get("location"))
    weather = parse_weather(body.get("weather"))
    arrays = parse_arrays(body.get("arrays"))
    results = []
    for array in arrays:
        ac_kw = simulate(lat, lon, elevation_m, weather, array)
        results.append(
            {
                "id": array.id,
                "capacity_kw": array.capacity_kw,
                "energy_kwh": round(sum(ac_kw), 3),
                "capacity_factor": [round(kw / array.capacity_kw, 4) for kw in ac_kw],
            }
        )
    return {
        "index": body["weather"]["index"],
        "unit": "kW AC per kW DC",
        "filled_values": weather.filled,
        "arrays": results,
    }


def _parse_location(location: object) -> tuple[float, float, float]:
    if not isinstance(location, dict):
        raise RequestError("invalid_location", "location must be an object with lat and lon")
    values = []
    for key, lo, hi, default in (("lat", -90, 90, None), ("lon", -180, 180, None), ("elevation_m", -500, 9000, 0.0)):
        value = location.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
            raise RequestError(
                "invalid_location", f"location.{key} is {value!r}, expected a number between {lo} and {hi}"
            )
        values.append(float(value))
    return values[0], values[1], values[2]


def _error(status: int, code: str, message: str, details: dict | None = None):
    body = {"code": code, "message": message}
    if details:
        body["details"] = details
    return jsonify(error=body), status
