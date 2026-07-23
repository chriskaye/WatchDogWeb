from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
from session import do_logout, get_active_token
from style import inject_css, badge
from battery import estimate_percentage, profile_by_id
from api_client import (
    ApiError,
    list_sites, list_gateways, list_sensors, list_alerts, get_sensor_readings,
    list_battery_profiles, get_me, get_my_roles, list_auth_methods,
    list_report_templates, list_user_reports, create_user_report, update_user_report, delete_user_report,
)

WINDOW_DAYS_OPTIONS = {"Last 24 hours": 1, "Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}


def _site_options(sites):
    by_label = {"All sites": None}
    for s in sites:
        by_label[f"{s['name']} (#{s['site_id']})"] = s["site_id"]
    return by_label


def _all_devices(gateways, sensors):
    devices = []
    for g in gateways:
        devices.append({"serial_number": g["serial_number"], "name": g["name"] or g["gateway_id"],
                         "site_id": g["site_id"], "kind": "gateway", "battery_profile_id": g.get("battery_profile_id")})
    for s in sensors:
        devices.append({"serial_number": s["serial_number"], "name": s["name"] or s["sensor_id"],
                         "site_id": s["site_id"], "kind": "sensor", "battery_profile_id": s.get("battery_profile_id")})
    return devices


def _fetch_readings_df(token, serial_number, days, metric=None):
    from_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
    try:
        readings = get_sensor_readings(token, serial_number, from_date=from_date, metric=metric, limit=5000).get("readings", [])
    except ApiError:
        readings = []
    if not readings:
        return pd.DataFrame()
    df = pd.DataFrame(readings)
    df["ts"] = pd.to_datetime(df["ts"])
    return df.sort_values("ts")


# =====================================================================================
# Report renderers — one per template key. Each takes (token, config, sites, gateways,
# sensors, battery_profiles, key_prefix) and writes directly to the page.
#
# key_prefix matters: the same renderer function runs once per template browsed in the
# "Report Templates" tab AND once per saved report (possibly several) referencing that
# same template in "My Reports" — all on the same page render. Every st.form key and
# every session_state key here is namespaced with key_prefix specifically to avoid
# Streamlit's "duplicate form key" crash and cross-instance session_state clobbering that
# a shared/hardcoded key would cause the moment two instances of the same template are on
# screen together (found by testing, not theoretical).
# =====================================================================================

def render_multi_sensor_comparison(token, config, sites, gateways, sensors, battery_profiles, key_prefix):
    devices = _all_devices(gateways, sensors)
    device_by_label = {f"{d['name']} ({d['kind']})": d for d in devices}
    if not device_by_label:
        st.info("No devices provisioned yet.")
        return None
    default_labels = [l for l, d in device_by_label.items() if d["serial_number"] in config.get("device_serials", [])]
    with st.form(f"cfg_multi_sensor_{key_prefix}", border=False):
        chosen_labels = st.multiselect("Devices", list(device_by_label.keys()), default=default_labels)
        metric = st.selectbox("Metric", ["temperature", "humidity", "battery"],
                               index=["temperature", "humidity", "battery"].index(config.get("metric", "temperature")))
        window_label = st.selectbox("Window", list(WINDOW_DAYS_OPTIONS.keys()), index=1)
        run = st.form_submit_button("Run", type="primary")
    result_key = f"report_result_multi_sensor_comparison_{key_prefix}"
    if run:
        st.session_state[result_key] = {
            "device_serials": [device_by_label[l]["serial_number"] for l in chosen_labels],
            "metric": metric, "window_days": WINDOW_DAYS_OPTIONS[window_label],
        }
    result_cfg = st.session_state.get(result_key) or config
    serials = result_cfg.get("device_serials", [])
    if not serials:
        st.caption("Choose one or more devices above and click Run.")
        return None
    series = {}
    for serial in serials:
        df = _fetch_readings_df(token, serial, result_cfg.get("window_days", 7), metric=result_cfg.get("metric", "temperature"))
        label = next((f"{d['name']}" for d in devices if d["serial_number"] == serial), serial)
        if not df.empty and result_cfg.get("metric", "temperature") in df.columns:
            series[label] = df.set_index("ts")[result_cfg.get("metric", "temperature")]
    if not series:
        st.info("No readings for the selected devices/window.")
    else:
        st.line_chart(pd.DataFrame(series))
    return result_cfg


def render_fleet_battery_health(token, config, sites, gateways, sensors, battery_profiles, key_prefix):
    site_by_label = _site_options(sites)
    with st.form(f"cfg_fleet_battery_{key_prefix}", border=False):
        site_label = st.selectbox("Site", list(site_by_label.keys()),
                                   index=list(site_by_label.values()).index(config.get("site_id")) if config.get("site_id") in site_by_label.values() else 0)
        run = st.form_submit_button("Run", type="primary")
    result_key = f"report_result_fleet_battery_health_{key_prefix}"
    if run:
        st.session_state[result_key] = {"site_id": site_by_label[site_label]}
    result_cfg = st.session_state.get(result_key) or config or {"site_id": None}
    site_id = result_cfg.get("site_id")
    devices = [d for d in _all_devices(gateways, sensors) if site_id is None or d["site_id"] == site_id]
    if not devices:
        st.info("No devices for this filter.")
        return result_cfg
    profile_lookup = profile_by_id(battery_profiles)
    rows = []
    for d in devices:
        df = _fetch_readings_df(token, d["serial_number"], 1, metric="battery")
        latest_v = df["battery"].dropna().iloc[-1] if not df.empty and "battery" in df.columns and df["battery"].notna().any() else None
        profile = profile_lookup.get(d["battery_profile_id"])
        pct = estimate_percentage(latest_v, profile["discharge_points"]) if (latest_v is not None and profile) else None
        rows.append({
            "Device": d["name"], "Type": d["kind"],
            "Battery type": profile["name"] if profile else "Not set",
            "Latest voltage": f"{latest_v:.2f} V" if latest_v is not None else "—",
            "Est. %": pct if pct is not None else float("nan"),
        })
    df_out = pd.DataFrame(rows).sort_values("Est. %", na_position="first")
    st.dataframe(df_out, hide_index=True, width="stretch")
    return result_cfg


def render_alert_history(token, config, sites, gateways, sensors, battery_profiles, key_prefix):
    status_options = ["All", "open", "acknowledged", "resolved"]
    with st.form(f"cfg_alert_history_{key_prefix}", border=False):
        status = st.selectbox("Status", status_options, index=status_options.index(config.get("status", "All")))
        run = st.form_submit_button("Run", type="primary")
    result_key = f"report_result_alert_history_{key_prefix}"
    if run:
        st.session_state[result_key] = {"status": status}
    result_cfg = st.session_state.get(result_key) or config or {"status": "All"}
    status = result_cfg.get("status", "All")
    try:
        alerts = list_alerts(token, status=None if status == "All" else status).get("alerts", [])
    except ApiError as e:
        alerts = []
        st.error(f"Could not load alerts: {e.detail}")
    if not alerts:
        st.info("No alerts for this filter.")
        return result_cfg
    df = pd.DataFrame(alerts)
    st.markdown("**By metric**")
    st.bar_chart(df["metric_name"].value_counts())
    st.markdown("**By device**")
    st.bar_chart(df["serial_number"].value_counts())
    st.markdown("**Raw list**")
    st.dataframe(
        df[["serial_number", "metric_name", "status", "triggered_value", "triggered_at"]]
        .sort_values("triggered_at", ascending=False),
        hide_index=True, width="stretch",
    )
    return result_cfg


def render_site_environmental_summary(token, config, sites, gateways, sensors, battery_profiles, key_prefix):
    site_by_label = _site_options(sites)
    labels_without_all = {k: v for k, v in site_by_label.items() if v is not None}
    if not labels_without_all:
        st.info("No sites yet.")
        return None
    with st.form(f"cfg_site_env_{key_prefix}", border=False):
        site_label = st.selectbox("Site*", list(labels_without_all.keys()))
        window_label = st.selectbox("Window", list(WINDOW_DAYS_OPTIONS.keys()), index=1)
        run = st.form_submit_button("Run", type="primary")
    result_key = f"report_result_site_environmental_summary_{key_prefix}"
    if run:
        st.session_state[result_key] = {
            "site_id": labels_without_all[site_label], "window_days": WINDOW_DAYS_OPTIONS[window_label],
        }
    result_cfg = st.session_state.get(result_key) or config
    site_id = result_cfg.get("site_id")
    if not site_id:
        st.caption("Choose a site above and click Run.")
        return None
    devices = [d for d in _all_devices(gateways, sensors) if d["site_id"] == site_id]
    rows = []
    for d in devices:
        df = _fetch_readings_df(token, d["serial_number"], result_cfg.get("window_days", 7))
        if df.empty:
            continue
        row = {"Device": d["name"]}
        for metric in ("temperature", "humidity"):
            if metric in df.columns and df[metric].notna().any():
                row[f"{metric} min"] = round(df[metric].min(), 1)
                row[f"{metric} max"] = round(df[metric].max(), 1)
                row[f"{metric} avg"] = round(df[metric].mean(), 1)
        rows.append(row)
    if not rows:
        st.info("No readings for this site/window yet.")
    else:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    return result_cfg


def render_offline_devices(token, config, sites, gateways, sensors, battery_profiles, key_prefix):
    site_by_label = _site_options(sites)
    with st.form(f"cfg_offline_{key_prefix}", border=False):
        site_label = st.selectbox("Site", list(site_by_label.keys()),
                                   index=list(site_by_label.values()).index(config.get("site_id")) if config.get("site_id") in site_by_label.values() else 0)
        threshold_hours = st.number_input("Offline threshold (hours)", min_value=1, value=int(config.get("threshold_hours", 24)))
        run = st.form_submit_button("Run", type="primary")
    result_key = f"report_result_offline_devices_{key_prefix}"
    if run:
        st.session_state[result_key] = {"site_id": site_by_label[site_label], "threshold_hours": threshold_hours}
    result_cfg = st.session_state.get(result_key) or config or {"site_id": None, "threshold_hours": 24}
    site_id = result_cfg.get("site_id")
    threshold_hours = result_cfg.get("threshold_hours", 24)
    devices = [d for d in _all_devices(gateways, sensors) if site_id is None or d["site_id"] == site_id]
    if not devices:
        st.info("No devices for this filter.")
        return result_cfg
    rows = []
    for d in devices:
        df = _fetch_readings_df(token, d["serial_number"], 30)
        last_seen = df["ts"].max() if not df.empty else None
        is_offline = last_seen is None or (datetime.utcnow() - last_seen.to_pydatetime().replace(tzinfo=None)) > timedelta(hours=threshold_hours)
        rows.append({
            "Device": d["name"],
            "Last seen": last_seen.strftime("%Y-%m-%d %H:%M") if last_seen is not None else "Never (last 30 days)",
            "Status": "Offline" if is_offline else "OK",
        })
    df_out = pd.DataFrame(rows)
    offline_count = (df_out["Status"] == "Offline").sum()
    if offline_count:
        st.warning(f"{offline_count} device(s) offline beyond the {threshold_hours}h threshold.")
    else:
        st.success("All devices reporting within the threshold.")
    st.dataframe(df_out, hide_index=True, width="stretch")
    return result_cfg


def render_mould_risk(token, config, sites, gateways, sensors, battery_profiles, key_prefix):
    devices = _all_devices(gateways, sensors)
    device_by_label = {f"{d['name']} ({d['kind']})": d for d in devices}
    if not device_by_label:
        st.info("No devices provisioned yet.")
        return None
    default_labels = [l for l, d in device_by_label.items() if d["serial_number"] in config.get("device_serials", [])]
    with st.form(f"cfg_mould_risk_{key_prefix}", border=False):
        chosen_labels = st.multiselect("Devices", list(device_by_label.keys()), default=default_labels)
        humidity_threshold = st.number_input("Humidity risk threshold (%)", min_value=0, max_value=100, value=int(config.get("humidity_threshold", 70)))
        temp_min = st.number_input("Risk temp range — min (°C)", value=float(config.get("temp_min", 15.0)))
        temp_max = st.number_input("Risk temp range — max (°C)", value=float(config.get("temp_max", 25.0)))
        window_label = st.selectbox("Window", list(WINDOW_DAYS_OPTIONS.keys()), index=1)
        run = st.form_submit_button("Run", type="primary")
    result_key = f"report_result_mould_risk_{key_prefix}"
    if run:
        st.session_state[result_key] = {
            "device_serials": [device_by_label[l]["serial_number"] for l in chosen_labels],
            "humidity_threshold": humidity_threshold, "temp_min": temp_min, "temp_max": temp_max,
            "window_days": WINDOW_DAYS_OPTIONS[window_label],
        }
    result_cfg = st.session_state.get(result_key) or config
    serials = result_cfg.get("device_serials", [])
    if not serials:
        st.caption(
            "Choose devices and click Run. Dwell time is estimated from the *sampling "
            "interval between readings*, not continuous monitoring — accurate to how "
            "often the device reports, not true continuous dwell time."
        )
        return None
    rows = []
    for serial in serials:
        df = _fetch_readings_df(token, serial, result_cfg.get("window_days", 7))
        label = next((d["name"] for d in devices if d["serial_number"] == serial), serial)
        if df.empty or "humidity" not in df.columns or "temperature" not in df.columns:
            rows.append({"Device": label, "Readings": 0, "Risk readings": 0, "Est. risk %": float("nan")})
            continue
        in_risk = (
            (df["humidity"] >= result_cfg.get("humidity_threshold", 70))
            & (df["temperature"] >= result_cfg.get("temp_min", 15))
            & (df["temperature"] <= result_cfg.get("temp_max", 25))
        )
        total = df["humidity"].notna().sum()
        risk_count = in_risk.sum()
        rows.append({
            "Device": label, "Readings": int(total), "Risk readings": int(risk_count),
            "Est. risk %": round(100 * risk_count / total, 1) if total else float("nan"),
        })
    st.dataframe(pd.DataFrame(rows).sort_values("Est. risk %", ascending=False), hide_index=True, width="stretch")
    return result_cfg


def render_motion_occupancy(token, config, sites, gateways, sensors, battery_profiles, key_prefix):
    devices = _all_devices(gateways, sensors)
    device_by_label = {f"{d['name']} ({d['kind']})": d for d in devices}
    if not device_by_label:
        st.info("No devices provisioned yet.")
        return None
    default_labels = [l for l, d in device_by_label.items() if d["serial_number"] in config.get("device_serials", [])]
    with st.form(f"cfg_motion_{key_prefix}", border=False):
        chosen_labels = st.multiselect("Devices", list(device_by_label.keys()), default=default_labels)
        window_label = st.selectbox("Window", list(WINDOW_DAYS_OPTIONS.keys()), index=1)
        run = st.form_submit_button("Run", type="primary")
    result_key = f"report_result_motion_occupancy_{key_prefix}"
    if run:
        st.session_state[result_key] = {
            "device_serials": [device_by_label[l]["serial_number"] for l in chosen_labels],
            "window_days": WINDOW_DAYS_OPTIONS[window_label],
        }
    result_cfg = st.session_state.get(result_key) or config
    serials = result_cfg.get("device_serials", [])
    if not serials:
        st.caption("Choose one or more devices above and click Run.")
        return None
    rows = []
    timelines = {}
    for serial in serials:
        df = _fetch_readings_df(token, serial, result_cfg.get("window_days", 7), metric="motion")
        label = next((d["name"] for d in devices if d["serial_number"] == serial), serial)
        if df.empty or "motion" not in df.columns:
            rows.append({"Device": label, "Motion events": 0})
            continue
        triggered = df[df["motion"] == True]
        rows.append({"Device": label, "Motion events": len(triggered)})
        if not triggered.empty:
            timelines[label] = triggered.set_index("ts")["motion"].astype(int)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if timelines:
        st.markdown("**Motion events timeline**")
        st.scatter_chart(pd.concat(timelines, axis=1))
    return result_cfg


def render_power_usage(token, config, sites, gateways, sensors, battery_profiles, key_prefix):
    st.warning(
        "No power/energy metric exists in `sensor_data` yet (columns are temperature, "
        "humidity, motion, battery) — this report has nothing to show until the ingest "
        "schema is extended with a power reading. Placeholder shipped now so the report "
        "slot and its config UI exist for when that data is available; not fabricating "
        "numbers in the meantime."
    )
    return None


def render_dsar_export(token, config, sites, gateways, sensors, battery_profiles, key_prefix):
    st.caption(
        "Exports your own account data — profile, roles, and login methods — as CSV. "
        "Scoped to your own record, not a full cross-table organisation export."
    )
    try:
        me = get_me(token)
        roles = get_my_roles(token)
        auth_methods = list_auth_methods(token).get("methods", [])
    except ApiError as e:
        st.error(f"Could not load your data: {e.detail}")
        return None
    rows = [
        {"field": "user_id", "value": me.get("user_id")},
        {"field": "email", "value": me.get("email")},
        {"field": "org_id", "value": me.get("org_id")},
        {"field": "is_watchdog_admin", "value": me.get("is_watchdog_admin")},
        {"field": "global_role", "value": roles.get("global_role")},
    ]
    for sr in roles.get("site_roles", []):
        rows.append({"field": f"site_role[{sr['site_id']}]", "value": sr["role"]})
    for m in auth_methods:
        rows.append({"field": f"auth_method[{m['method_type']}]", "value": m.get("provider_sub") or "linked"})
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, width="stretch")
    st.download_button(
        "Download as CSV", df.to_csv(index=False).encode("utf-8"),
        file_name="my_data_export.csv", mime="text/csv", key=f"dsar_dl_{key_prefix}",
    )
    return None  # nothing meaningful to save/customize for this one


RENDERERS = {
    "multi_sensor_comparison": render_multi_sensor_comparison,
    "fleet_battery_health": render_fleet_battery_health,
    "alert_history": render_alert_history,
    "site_environmental_summary": render_site_environmental_summary,
    "offline_devices": render_offline_devices,
    "mould_risk": render_mould_risk,
    "motion_occupancy": render_motion_occupancy,
    "power_usage": render_power_usage,
    "dsar_export": render_dsar_export,
}

# =====================================================================================
# Page
# =====================================================================================

st.set_page_config(page_title="Reports", page_icon="favicon.ico", layout="wide")
inject_css()

if st.session_state.get("logged_in"):
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=do_logout)

token = get_active_token()
in_support_view = st.session_state.get("support_session") is not None

st.markdown("## Reports")
if in_support_view:
    st.info("Viewing reports in read-only Support Access mode — saving a report is disabled.")

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
    battery_profiles = list_battery_profiles(token).get("battery_profiles", [])
except ApiError:
    battery_profiles = []
try:
    templates = list_report_templates(token).get("report_templates", [])
except ApiError as e:
    templates = []
    st.error(f"Could not load report templates: {e.detail}")

tab_templates, tab_saved = st.tabs(["Report Templates", "My Reports"])

with tab_templates:
    categories = sorted({t["category"] for t in templates})
    for category in categories:
        st.markdown(f"### {category.replace('_', ' ').title()}")
        for t in [x for x in templates if x["category"] == category]:
            with st.expander(t["name"]):
                st.caption(t["description"])
                renderer = RENDERERS.get(t["key"])
                if not renderer:
                    st.error("No renderer implemented for this template yet.")
                    continue
                key_prefix = f"tmpl_{t['key']}"
                used_cfg = renderer(token, {}, sites, gateways, sensors, battery_profiles, key_prefix)
                if used_cfg:
                    with st.form(f"save_{key_prefix}", border=False):
                        save_name = st.text_input("Save this configuration as", key=f"save_name_{key_prefix}")
                        save_submit = st.form_submit_button("Save as My Report", disabled=in_support_view)
                    if save_submit:
                        if not save_name.strip():
                            st.error("Give the saved report a name.")
                        else:
                            try:
                                create_user_report(token, t["report_template_id"], save_name.strip(), used_cfg)
                                st.success(f"Saved '{save_name}'.")
                            except ApiError as e:
                                st.error(f"Could not save: {e.detail}")

with tab_saved:
    try:
        user_reports = list_user_reports(token).get("user_reports", [])
    except ApiError as e:
        user_reports = []
        st.error(f"Could not load your saved reports: {e.detail}")

    if not user_reports:
        st.info("No saved reports yet — configure a template in the Report Templates tab and click 'Save as My Report'.")
    else:
        for ur in user_reports:
            with st.expander(f"{ur['name']} — {ur['template_name']}"):
                renderer = RENDERERS.get(ur["template_key"])
                if not renderer:
                    st.error("No renderer implemented for this template yet.")
                else:
                    key_prefix = f"saved_{ur['user_report_id']}"
                    renderer(token, ur["config"], sites, gateways, sensors, battery_profiles, key_prefix)
                st.markdown("---")
                st.markdown("**Manage this report**")
                with st.form(f"rename_{ur['user_report_id']}", border=False):
                    rc1, rc2 = st.columns([3, 1])
                    with rc1:
                        new_name = st.text_input("Rename", value=ur["name"], key=f"rename_input_{ur['user_report_id']}")
                    with rc2:
                        st.write("")
                        rename_submit = st.form_submit_button("Save Name", disabled=in_support_view)
                if rename_submit:
                    if not new_name.strip():
                        st.error("Name can't be empty.")
                    else:
                        try:
                            update_user_report(token, ur["user_report_id"], name=new_name.strip())
                            st.success("Renamed.")
                            st.rerun()
                        except ApiError as e:
                            st.error(f"Could not rename: {e.detail}")
                mc1, mc2 = st.columns(2)
                with mc1:
                    if st.button("Duplicate", key=f"dup_ur_{ur['user_report_id']}", disabled=in_support_view):
                        try:
                            create_user_report(token, ur["report_template_id"], f"{ur['name']} (copy)", ur["config"])
                            st.success("Duplicated.")
                            st.rerun()
                        except ApiError as e:
                            st.error(f"Could not duplicate: {e.detail}")
                with mc2:
                    if st.button("Delete", key=f"del_ur_{ur['user_report_id']}", disabled=in_support_view):
                        try:
                            delete_user_report(token, ur["user_report_id"])
                            st.rerun()
                        except ApiError as e:
                            st.error(f"Could not delete: {e.detail}")
