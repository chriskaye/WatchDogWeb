def estimate_percentage(voltage_v: float, discharge_points: list[dict]) -> float | None:
    """Linear-interpolates an estimated remaining-charge percentage from a raw voltage
    reading against a battery profile's discharge_points (each {"voltage_mv", "percentage"}).
    Returns None if there are no points to interpolate against. Clamps to the curve's own
    endpoints outside its range rather than extrapolating."""
    if not discharge_points:
        return None
    voltage_mv = voltage_v * 1000
    pts = sorted(discharge_points, key=lambda p: p["voltage_mv"], reverse=True)
    if voltage_mv >= pts[0]["voltage_mv"]:
        return float(pts[0]["percentage"])
    if voltage_mv <= pts[-1]["voltage_mv"]:
        return float(pts[-1]["percentage"])
    for hi, lo in zip(pts, pts[1:]):
        if lo["voltage_mv"] <= voltage_mv <= hi["voltage_mv"]:
            span = hi["voltage_mv"] - lo["voltage_mv"]
            if span == 0:
                return float(hi["percentage"])
            frac = (voltage_mv - lo["voltage_mv"]) / span
            return round(lo["percentage"] + frac * (hi["percentage"] - lo["percentage"]), 1)
    return None


def profile_by_id(battery_profiles: list[dict]) -> dict:
    return {p["battery_profile_id"]: p for p in battery_profiles}
