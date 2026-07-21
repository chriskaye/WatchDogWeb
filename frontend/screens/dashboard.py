import streamlit as st
from session import do_logout, get_active_token
from style import inject_css, badge
from api_client import ApiError, list_sites, list_gateways, list_sensors

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
    st.markdown(f'<div class="card">Active Alerts<br><h3>—</h3></div>', unsafe_allow_html=True)
    st.caption("No alerts feed endpoint yet — see outstanding tasks.")

st.markdown("---")

if not sites:
    st.info("No sites yet. Head to **Configuration → Sites** to create your first one, then provision a gateway or sensor.")
else:
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
            if site_sensors:
                st.markdown("**Sensors**")
                for s in site_sensors:
                    sb = badge("Active", "ok") if s["is_active"] else badge("Inactive", "muted")
                    st.markdown(f"- {s['name'] or s['sensor_id']} ({s.get('location') or 'no location'}) {sb}", unsafe_allow_html=True)
            if not site_gateways and not site_sensors:
                st.caption("No devices provisioned at this site yet.")

    st.markdown("---")
    st.markdown("### Recent readings")
    st.info(
        "Live sensor readings and trend charts need a time-series read endpoint "
        "(e.g. GET /sensors/{id}/readings) that doesn't exist yet — device_latest_status "
        "exists server-side but isn't exposed via the API. Tracked in outstanding tasks."
    )
