from datetime import datetime, timedelta
import streamlit as st
from session import do_logout, get_active_token
from style import inject_css, badge
from battery import estimate_percentage, profile_by_id
import pandas as pd
from api_client import (
    ApiError, list_sites, list_gateways, list_sensors, list_alerts, get_sensor_readings,
    list_battery_profiles,
)

st.set_page_config(page_title="Dashboard", page_icon="favicon.ico", layout="wide")
inject_css()

if st.session_state.get("logged_in"):
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=do_logout)

token = get_active_token()
user = st.session_state.get("user") or {}
in_support_view = st.session_state.get("support_session") is not None

st.markdown(f"## Dashboard")
if in_support_view:
    st.warning(f"Viewing **{st.session_state.support_session['target_email']}**'s data in read-only Support Access mode.")
else:
    st.caption(f"Welcome back, {user.get('email', '')}")

try:
    sites = list_sites(token).get("sites", [])
except ApiError as e:
    sites = []
    st.error(f"Could not load sites: {e.detail}")

try:
    gateways = list_gateways(token).get("gateways", [])
except ApiError as e:
    gateways = []
    st.error(f"Could not load gateways: {e.detail}")

try:
    sensors = list_sensors(token).get("sensors", [])
except ApiError as e:
    sensors = []
    st.error(f"Could not load sensors: {e.detail}")

try:
    open_alerts = list_alerts(token, status="open").get("alerts", [])
except ApiError as e:
    open_alerts = []
    st.error(f"Could not load alerts: {e.detail}")

active_gateways = sum(1 for g in gateways if g["is_active"])
active_sensors = sum(1 for s in sensors if s["is_active"])

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f'<div class="card">Sites<br><h3>{len(sites)}</h3></div>', unsafe_allow_html=True)
with c2:
    st.markdown(f'<div class="card">Gateways<br><h3>{active_gateways}/{len(gateways)} active</h3></div>', unsafe_allow_html=True)
with c3:
    st.markdown(f'<div class="card">Sensors<br><h3>{active_sensors}/{len(sensors)} active</h3></div>', unsafe_allow_html=True)
with c4:
    st.markdown(
        f'<div class="card">Active Alerts<br><h3 style="color:{"#ff6b6b" if open_alerts else "inherit"}">{len(open_alerts)}</h3></div>',
        unsafe_allow_html=True,
    )

st.markdown("---")

# =====================================================================================
# Alerts feed
# =====================================================================================
st.markdown("### Alerts")
alert_filter = st.radio("Show", ["Open", "Acknowledged", "Resolved", "All"], horizontal=True, key="alert_status_filter")
status_map = {"Open": "open", "Acknowledged": "acknowledged", "Resolved": "resolved", "All": None}
try:
    feed_alerts = list_alerts(token, status=status_map[alert_filter]).get("alerts", [])
except ApiError as e:
    feed_alerts = []
    st.error(f"Could not load alerts: {e.detail}")

if not feed_alerts:
    st.info(f"No {alert_filter.lower()} alerts." if alert_filter != "All" else "No alerts.")
else:
    status_kind = {"open": "danger", "acknowledged": "warn", "resolved": "ok"}
    for a in feed_alerts:
        c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
        with c1:
            st.write(f"**{a['serial_number']}**")
        with c2:
            st.write(a["metric_name"])
        with c3:
            st.write(f"Value: {a['triggered_value']}")
        with c4:
            st.markdown(badge(a["status"], status_kind.get(a["status"], "muted")), unsafe_allow_html=True)
        st.caption(f"Triggered: {a.get('triggered_at', '—')}")
        st.markdown("&nbsp;", unsafe_allow_html=True)

st.markdown("---")

def _latest_glance(serial_number, profile_by_id_lookup, battery_profile_id):
    """RPT-3: at-a-glance status for a device row in Sites Overview — last-seen recency,
    latest temp/humidity, and estimated battery % if a profile is assigned. One lightweight
    readings call per device; fine at current fleet sizes, revisit if this page gets slow
    with large fleets (same scale caveat as RPT-1 itself)."""
    from_date = (datetime.utcnow() - timedelta(days=30)).isoformat()
    try:
        readings = get_sensor_readings(get_active_token(), serial_number, from_date=from_date, limit=1).get("readings", [])
    except ApiError:
        readings = []
    if not readings:
        return "No readings in the last 30 days"
    r = readings[0]
    ts = datetime.fromisoformat(r["ts"]).replace(tzinfo=None)
    age = datetime.utcnow() - ts
    if age < timedelta(hours=1):
        freshness = f"{int(age.total_seconds() // 60)}m ago"
    elif age < timedelta(days=1):
        freshness = f"{int(age.total_seconds() // 3600)}h ago"
    else:
        freshness = f"{age.days}d ago"
    parts = [f"Last seen {freshness}"]
    if r.get("temperature") is not None:
        parts.append(f"{r['temperature']:.1f}°C")
    if r.get("humidity") is not None:
        parts.append(f"{r['humidity']:.0f}% RH")
    if r.get("battery") is not None:
        profile = profile_by_id_lookup.get(battery_profile_id)
        pct = estimate_percentage(r["battery"], profile["discharge_points"]) if profile else None
        parts.append(f"{pct:.0f}% batt" if pct is not None else f"{r['battery']:.2f}V batt")
    return " · ".join(parts)


if not sites:
    st.info("No sites yet. Head to **Configuration → Sites** to create your first one, then provision a gateway or sensor.")
else:
    try:
        overview_battery_profiles = list_battery_profiles(token).get("battery_profiles", [])
    except ApiError:
        overview_battery_profiles = []
    overview_profile_by_id = profile_by_id(overview_battery_profiles)

    st.markdown("### Sites Overview")
    site_by_id = {s["site_id"]: s for s in sites}
    for site in sites:
        site_gateways = [g for g in gateways if g["site_id"] == site["site_id"]]
        site_sensors = [s for s in sensors if s["site_id"] == site["site_id"]]
        with st.expander(f"{site['name']} — {len(site_gateways)} gateway(s), {len(site_sensors)} sensor(s)"):
            status_badge = badge("Active", "ok") if site["is_active"] else badge("Inactive", "muted")
            st.markdown(status_badge, unsafe_allow_html=True)
            if site_gateways:
                st.markdown("**Gateways**")
                for g in site_gateways:
                    gb = badge("Active", "ok") if g["is_active"] else badge("Inactive", "muted")
                    st.markdown(f"- {g['name'] or g['gateway_id']} {gb}", unsafe_allow_html=True)
                    st.caption(_latest_glance(g["serial_number"], overview_profile_by_id, g.get("battery_profile_id")))
            if site_sensors:
                st.markdown("**Sensors**")
                for s in site_sensors:
                    sb = badge("Active", "ok") if s["is_active"] else badge("Inactive", "muted")
                    st.markdown(f"- {s['name'] or s['sensor_id']} ({s.get('location') or 'no location'}) {sb}", unsafe_allow_html=True)
                    st.caption(_latest_glance(s["serial_number"], overview_profile_by_id, s.get("battery_profile_id")))
            if not site_gateways and not site_sensors:
                st.caption("No devices provisioned at this site yet.")

    st.markdown("---")
    st.markdown("### Recent readings")
    all_devices = (
        [{"label": f"{g['name'] or g['gateway_id']} (gateway)", "serial_number": g["serial_number"],
          "battery_profile_id": g.get("battery_profile_id")} for g in gateways]
        + [{"label": f"{s['name'] or s['sensor_id']} (sensor)", "serial_number": s["serial_number"],
            "battery_profile_id": s.get("battery_profile_id")} for s in sensors]
    )
    if not all_devices:
        st.caption("No devices provisioned yet.")
    else:
        try:
            battery_profiles = list_battery_profiles(token).get("battery_profiles", [])
        except ApiError:
            battery_profiles = []
        battery_profile_by_id = profile_by_id(battery_profiles)

        device_by_label = {d["label"]: d for d in all_devices}
        chosen_label = st.selectbox("Device", list(device_by_label.keys()), key="readings_device_select")
        chosen_device = device_by_label[chosen_label]
        # I edited this to show more granular timeframes, 1h, 6h, 12h
        window_label = st.radio("Window", ["Last 1h", "Last 6h", "Last 12h", "Last 24h", "Last 7 days", "Last 30 days"], horizontal=True, key="readings_window")
        window_hours = {"Last 1h":1, "Last 6h":6, "Last 12h":12, "Last 24h": 24, "Last 7 days": 24 * 7, "Last 30 days": 24 * 30}[window_label]
        from_date = (datetime.utcnow() - timedelta(hours=window_hours)).isoformat()

        try:
            readings = get_sensor_readings(
                token, chosen_device["serial_number"], from_date=from_date, limit=2000,
            ).get("readings", [])
        except ApiError as e:
            readings = []
            st.error(f"Could not load readings: {e.detail}")

        if not readings:
            st.info("No readings for this device in the selected window yet.")
        else:
            df = pd.DataFrame(readings)
            df["ts"] = pd.to_datetime(df["ts"])
            df = df.sort_values("ts").set_index("ts")
            numeric_cols = [c for c in ("temperature", "humidity", "battery") if c in df.columns and df[c].notna().any()]
            if numeric_cols:
                st.line_chart(df[numeric_cols])
            if "motion" in df.columns and df["motion"].notna().any():
                st.caption("Motion (most recent readings)")
                st.dataframe(df[["motion"]].tail(50).iloc[::-1], width="stretch")

            if "battery" in df.columns and df["battery"].notna().any():
                st.markdown("#### Battery")
                profile = battery_profile_by_id.get(chosen_device["battery_profile_id"])
                if not profile:
                    st.caption(
                        "No battery type set for this device — add one in Configuration → "
                        "Devices to see an estimated remaining-charge percentage here "
                        "(or set it to 'Not powered by batteries' if it's mains/PoE-powered)."
                    )
                else:
                    latest_voltage = df["battery"].dropna().iloc[-1]
                    latest_pct = estimate_percentage(latest_voltage, profile["discharge_points"])
                    mc1, mc2 = st.columns(2)
                    with mc1:
                        st.metric("Latest voltage", f"{latest_voltage:.2f} V")
                    with mc2:
                        st.metric(
                            "Estimated remaining charge",
                            f"{latest_pct:.0f}%" if latest_pct is not None else "—",
                        )
                    pct_series = df["battery"].apply(
                        lambda v: estimate_percentage(v, profile["discharge_points"]) if pd.notna(v) else None
                    )
                    if pct_series.notna().any():
                        st.line_chart(pct_series.rename("estimated %"))
                    st.caption(
                        f"Against the '{profile['name']}' discharge curve — a generic approximation "
                        "for this chemistry, not a manufacturer-specific datasheet value."
                    )