import streamlit as st
from session import do_logout, get_active_token
from style import inject_css, badge
from api_client import (
    ApiError,
    list_sites, create_site, update_site, delete_site,
    list_gateways, list_sensors, soft_delete_gateway, soft_delete_sensor,
    check_device, activate_device, deprovision_device, factory_reset_device,
    list_node_templates, create_node_template, delete_node_template,
    list_mcu_variants, list_gpio_pins,
    list_sensor_module_types,
    list_node_template_module_pins, add_node_template_module_pin, delete_node_template_module_pin,
    list_module_pin_gpio_assignments, add_module_pin_gpio_assignment, delete_module_pin_gpio_assignment,
    list_alert_templates, create_alert_template, delete_alert_template,
    add_alert_template_rule, delete_alert_template_rule,
    list_alert_rules, create_alert_rule, delete_alert_rule,
    list_battery_profiles, set_gateway_battery_profile, set_sensor_battery_profile,
)

NOT_BATTERY_POWERED = "Not powered by batteries"


def _battery_profile_options(battery_profiles):
    """Returns (id_by_label, ordered_labels) with NOT_BATTERY_POWERED always first."""
    by_label = {NOT_BATTERY_POWERED: None}
    for p in battery_profiles:
        by_label[f"{p['name']} ({p['nominal_voltage_mv'] / 1000:.1f}V nominal)"] = p["battery_profile_id"]
    return by_label, list(by_label.keys())


def _label_for_battery_profile(battery_profiles, battery_profile_id):
    if battery_profile_id is None:
        return NOT_BATTERY_POWERED
    for p in battery_profiles:
        if p["battery_profile_id"] == battery_profile_id:
            return f"{p['name']} ({p['nominal_voltage_mv'] / 1000:.1f}V nominal)"
    return f"Unknown profile #{battery_profile_id}"


def _battery_control(device_id: str, is_gateway: bool, current_battery_profile_id, battery_profiles, disabled: bool):
    """Battery-type control per device row, same toggle-to-expand pattern as Factory Reset
    and Alert Rules — shows the current profile and lets it be changed or cleared."""
    key_prefix = f"battery_{device_id}"
    if st.button("Battery", key=f"{key_prefix}_open", disabled=disabled):
        st.session_state[f"{key_prefix}_show"] = not st.session_state.get(f"{key_prefix}_show", False)
    if not st.session_state.get(f"{key_prefix}_show"):
        return

    by_label, labels = _battery_profile_options(battery_profiles)
    current_label = _label_for_battery_profile(battery_profiles, current_battery_profile_id)
    st.caption(f"Current: {current_label}")
    with st.form(f"{key_prefix}_form", border=False):
        chosen_label = st.selectbox(
            "Battery type", labels,
            index=labels.index(current_label) if current_label in labels else 0,
            key=f"{key_prefix}_select",
        )
        save = st.form_submit_button("Save", disabled=disabled)
    if save:
        token = get_active_token()
        try:
            if is_gateway:
                set_gateway_battery_profile(token, device_id, by_label[chosen_label])
            else:
                set_sensor_battery_profile(token, device_id, by_label[chosen_label])
            st.success("Battery type updated.")
            st.rerun()
        except ApiError as e:
            st.error(f"Could not update battery type: {e.detail}")

METRIC_OPTIONS = ["temperature", "humidity", "battery", "motion"]


def _metric_threshold_inputs(key_prefix: str):
    """Shared metric/threshold picker for both Alert Templates and per-device Alert
    Rules — the backend's validate_alert_rule_shape() requires exactly one of
    threshold_min/max (numeric metrics) or trigger_value (motion, boolean), never both.
    Returns (metric_name, threshold_min, threshold_max, trigger_value).
    """
    metric_name = st.selectbox("Metric", METRIC_OPTIONS, key=f"{key_prefix}_metric")
    if metric_name == "motion":
        trigger_value = st.selectbox("Trigger when motion is", [True, False], key=f"{key_prefix}_trigger")
        return metric_name, None, None, trigger_value
    col_a, col_b = st.columns(2)
    with col_a:
        threshold_min = st.number_input(
            "Min (leave at 0 to omit if only using Max)", value=0.0, key=f"{key_prefix}_min",
        )
    with col_b:
        threshold_max = st.number_input(
            "Max (leave at 0 to omit if only using Min)", value=0.0, key=f"{key_prefix}_max",
        )
    # Streamlit's number_input has no clean "unset" state — 0.0 doubles as a real possible
    # threshold for humidity/battery, so this can't perfectly distinguish "meant zero" from
    # "left blank". Acceptable trade-off for now; flagged rather than silently assuming.
    return metric_name, (threshold_min or None), (threshold_max or None), None


def _alert_rules_control(serial_number: str, disabled: bool):
    """Per-device Alert Rules management — list/add/delete, shown inline below the device
    row when toggled open. Direct rule editing (not template-based)."""
    key_prefix = f"alert_rules_{serial_number}"
    if st.button("Alert Rules", key=f"{key_prefix}_open", disabled=disabled):
        st.session_state[f"{key_prefix}_show"] = not st.session_state.get(f"{key_prefix}_show", False)
    if st.session_state.get(f"{key_prefix}_show"):
        try:
            rules = list_alert_rules(get_active_token(), serial_number).get("alert_rules", [])
        except ApiError as e:
            rules = []
            st.error(f"Could not load alert rules: {e.detail}")

        if not rules:
            st.caption("No alert rules for this device yet.")
        else:
            for r in [x for x in rules if x["is_active"]]:
                rc1, rc2, rc3 = st.columns([2, 3, 1])
                with rc1:
                    st.write(f"**{r['metric_name']}**")
                with rc2:
                    if r["metric_name"] == "motion":
                        st.write(f"Trigger: {r['trigger_value']}")
                    else:
                        st.write(f"Min: {r['threshold_min']}, Max: {r['threshold_max']}")
                with rc3:
                    if st.button("Delete", key=f"{key_prefix}_del_{r['alert_rule_id']}", disabled=disabled):
                        try:
                            delete_alert_rule(get_active_token(), r["alert_rule_id"])
                            st.rerun()
                        except ApiError as e:
                            st.error(f"Could not delete rule: {e.detail}")

        with st.expander("Add alert rule"):
            metric_name, threshold_min, threshold_max, trigger_value = _metric_threshold_inputs(key_prefix)
            if st.button("Save Rule", key=f"{key_prefix}_save", disabled=disabled):
                try:
                    create_alert_rule(
                        get_active_token(), serial_number, metric_name,
                        threshold_min=threshold_min, threshold_max=threshold_max, trigger_value=trigger_value,
                    )
                    st.success("Alert rule saved.")
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not save rule: {e.detail}")


def _module_pins_control(node_template: dict, disabled: bool):
    """Node Template -> Sensor Module -> GPIO pin nested editor, shown inline below a
    template row when toggled open. Three levels: pick which sensor module types this
    template uses (module pins), then for each one assign its GPIO pin(s) (pin_role ->
    gpio_pin) against the template's own mcu_variant's GPIO catalog."""
    node_template_id = node_template["node_template_id"]
    key_prefix = f"module_pins_{node_template_id}"
    if st.button("Sensor Modules", key=f"{key_prefix}_open", disabled=disabled):
        st.session_state[f"{key_prefix}_show"] = not st.session_state.get(f"{key_prefix}_show", False)
    if not st.session_state.get(f"{key_prefix}_show"):
        return

    token = get_active_token()
    try:
        module_types = list_sensor_module_types(token).get("module_types", [])
    except ApiError as e:
        module_types = []
        st.error(f"Could not load sensor module types: {e.detail}")
    module_type_by_id = {m["module_type_id"]: m for m in module_types}

    try:
        gpio_catalog = list_gpio_pins(token, node_template["mcu_variant_id"]).get("gpio_pins", [])
    except ApiError as e:
        gpio_catalog = []
        st.error(f"Could not load GPIO pin catalog: {e.detail}")
    # Reserved/restricted pins are still shown for context but flagged — the backend
    # rejects assigning them, this just saves a round trip for the obvious case.
    gpio_pin_labels = [f"{p['gpio_pin']}" + ("" if p["status"] == "available" else f" ({p['status']})") for p in gpio_catalog]
    gpio_pin_by_label = {label: p["gpio_pin"] for label, p in zip(gpio_pin_labels, gpio_catalog)}

    try:
        module_pins = list_node_template_module_pins(token, node_template_id).get("module_pins", [])
    except ApiError as e:
        module_pins = []
        st.error(f"Could not load assigned modules: {e.detail}")

    if not module_pins:
        st.caption("No sensor modules assigned to this template yet.")
    for mp in module_pins:
        mp_id = mp["node_template_module_pin_id"]
        mtype = module_type_by_id.get(mp["module_type_id"])
        mtype_name = mtype["name"] if mtype else f"module_type_id {mp['module_type_id']}"
        mc1, mc2, mc3 = st.columns([3, 3, 1])
        with mc1:
            st.write(f"**{mtype_name}**")
        with mc2:
            st.caption(f"I2C override: {mp['i2c_address_override'] or 'default'}")
        with mc3:
            if st.button("Remove", key=f"{key_prefix}_rm_{mp_id}", disabled=disabled):
                try:
                    delete_node_template_module_pin(token, node_template_id, mp_id)
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not remove module: {e.detail}")

        try:
            gpio_assignments = list_module_pin_gpio_assignments(token, mp_id).get("gpio_assignments", [])
        except ApiError as e:
            gpio_assignments = []
            st.error(f"Could not load GPIO assignments: {e.detail}")

        for ga in gpio_assignments:
            gc1, gc2, gc3 = st.columns([2, 2, 1])
            with gc1:
                st.caption(f"Role: {ga['pin_role']}")
            with gc2:
                st.caption(f"Pin: {ga['gpio_pin']}")
            with gc3:
                if st.button("✕", key=f"{key_prefix}_{mp_id}_rmga_{ga['node_template_module_gpio_pin_id']}", disabled=disabled):
                    try:
                        delete_module_pin_gpio_assignment(token, mp_id, ga["node_template_module_gpio_pin_id"])
                        st.rerun()
                    except ApiError as e:
                        st.error(f"Could not remove GPIO assignment: {e.detail}")

        with st.expander(f"Assign a GPIO pin to {mtype_name}"):
            if not gpio_pin_labels:
                st.caption("No GPIO pins recorded for this template's MCU variant yet.")
            else:
                pin_role = st.text_input("Pin role (e.g. data, clock, power)", key=f"{key_prefix}_{mp_id}_role")
                pin_label = st.selectbox("GPIO pin", gpio_pin_labels, key=f"{key_prefix}_{mp_id}_pin")
                if st.button("Assign Pin", key=f"{key_prefix}_{mp_id}_assign", disabled=disabled):
                    if not pin_role.strip():
                        st.error("Pin role is required.")
                    else:
                        try:
                            add_module_pin_gpio_assignment(
                                token, mp_id, pin_role=pin_role.strip(), gpio_pin=gpio_pin_by_label[pin_label],
                            )
                            st.success("GPIO pin assigned.")
                            st.rerun()
                        except ApiError as e:
                            st.error(f"Could not assign pin: {e.detail}")
        st.markdown("---")

    with st.expander("Add a sensor module to this template"):
        if not module_types:
            st.caption("No sensor module types exist yet — a WatchDog platform admin needs to add one first.")
        else:
            mtype_labels = {m["name"]: m for m in module_types}
            chosen_label = st.selectbox("Sensor module type", list(mtype_labels.keys()), key=f"{key_prefix}_add_type")
            i2c_override = st.text_input("I2C address override (optional)", key=f"{key_prefix}_add_i2c")
            if st.button("Add Module", key=f"{key_prefix}_add_submit", disabled=disabled):
                try:
                    add_node_template_module_pin(
                        token, node_template_id,
                        module_type_id=mtype_labels[chosen_label]["module_type_id"],
                        i2c_address_override=i2c_override or None,
                    )
                    st.success(f"{chosen_label} added.")
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not add module: {e.detail}")


def _factory_reset_control(serial_number: str, disabled: bool):
    """Shared factory-reset confirm flow for both gateway and sensor rows."""
    key_prefix = f"factory_reset_{serial_number}"
    if st.button("Factory Reset", key=f"{key_prefix}_open", disabled=disabled):
        st.session_state[f"{key_prefix}_show"] = True
    if st.session_state.get(f"{key_prefix}_show"):
        st.warning(
            f"Factory reset **{serial_number}**? This unlinks it from your organisation/site "
            "so it can be resold or reprovisioned."
        )
        wait_for_confirmation = st.checkbox(
            "Wait for device to confirm the wipe before clearing links (recommended)",
            value=True, key=f"{key_prefix}_wait",
        )
        if not wait_for_confirmation:
            st.caption(
                "⚠️ Links will be cleared immediately, before the physical device has "
                "actually wiped — only use this if you know the device is unreachable or "
                "you're testing the API path (firmware doesn't act on factory_reset jobs yet)."
            )
        cc1, cc2 = st.columns(2)
        with cc1:
            if st.button("Confirm Factory Reset", key=f"{key_prefix}_confirm"):
                try:
                    result = factory_reset_device(token, serial_number, wait_for_confirmation)
                    st.session_state[f"{key_prefix}_show"] = False
                    if result.get("confirmation_required"):
                        st.success(f"Factory reset queued for {serial_number} — waiting for device confirmation.")
                    else:
                        st.success(f"Factory reset completed for {serial_number}.")
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not factory reset: {e.detail}")
        with cc2:
            if st.button("Cancel", key=f"{key_prefix}_cancel"):
                st.session_state[f"{key_prefix}_show"] = False
                st.rerun()

st.set_page_config(page_title="Configuration", page_icon="favicon.ico", layout="wide")
inject_css()

if st.session_state.get("logged_in"):
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=do_logout)

token = get_active_token()
in_support_view = st.session_state.get("support_session") is not None

st.markdown("## Configuration")
if in_support_view:
    st.warning(
        f"Viewing **{st.session_state.support_session['target_email']}**'s configuration "
        "in read-only Support Access mode. Changes below are disabled."
    )


def _site_options():
    """Returns (id_by_label, ordered_labels) for every site the user can see."""
    try:
        sites = list_sites(token).get("sites", [])
    except ApiError as e:
        st.error(f"Could not load sites: {e.detail}")
        return {}, []
    by_label = {}
    for s in sites:
        label = f"{s['name']} (#{s['site_id']})" + ("" if s["is_active"] else " — inactive")
        by_label[label] = s
    return by_label, list(by_label.keys())


tab_sites, tab_devices, tab_provision, tab_templates, tab_alert_templates = st.tabs(
    ["Sites", "Devices", "Provisioning", "Node Templates", "Alert Templates"]
)

# =====================================================================================
# Sites
# =====================================================================================
with tab_sites:
    st.markdown("### Sites")
    try:
        sites = list_sites(token).get("sites", [])
    except ApiError as e:
        sites = []
        st.error(f"Could not load sites: {e.detail}")

    if sites:
        st.dataframe(
            [{"Name": s["name"], "City": s.get("city") or "—", "Country": s.get("country") or "—",
              "Status": "Active" if s["is_active"] else "Inactive", "ID": s["site_id"]} for s in sites],
            hide_index=True, width="stretch",
        )
    else:
        st.info("No sites yet — create one below.")

    with st.expander("Add a new site"):
        with st.form("create_site_form", border=False):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("Site name*")
                address_line1 = st.text_input("Address line 1")
                city = st.text_input("City")
            with c2:
                country = st.text_input("Country")
                address_line2 = st.text_input("Address line 2")
                postcode = st.text_input("Postcode")
            submitted = st.form_submit_button("Create Site", type="primary", disabled=in_support_view)

        if submitted:
            if not name.strip():
                st.error("Site name is required.")
            else:
                try:
                    create_site(
                        token, name=name, address_line1=address_line1 or None,
                        address_line2=address_line2 or None, city=city or None,
                        postcode=postcode or None, country=country or None,
                    )
                    st.success(f"Site '{name}' created.")
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not create site: {e.detail}")

    if sites:
        with st.expander("Edit or deactivate a site"):
            labels = {f"{s['name']} (#{s['site_id']})": s for s in sites}
            chosen_label = st.selectbox("Site", list(labels.keys()), key="edit_site_select")
            chosen = labels[chosen_label]
            with st.form("edit_site_form", border=False):
                new_name = st.text_input("Name", value=chosen["name"])
                new_city = st.text_input("City", value=chosen.get("city") or "")
                new_country = st.text_input("Country", value=chosen.get("country") or "")
                colA, colB = st.columns(2)
                with colA:
                    save = st.form_submit_button("Save Changes", type="primary", disabled=in_support_view)
                with colB:
                    deactivate = st.form_submit_button("Deactivate Site", type="secondary", disabled=in_support_view)

            if save:
                try:
                    update_site(token, chosen["site_id"], name=new_name, city=new_city or None, country=new_country or None)
                    st.success("Site updated.")
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not update site: {e.detail}")
            if deactivate:
                try:
                    delete_site(token, chosen["site_id"])
                    st.success("Site deactivated.")
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not deactivate site: {e.detail}")

# =====================================================================================
# Devices (gateways + sensors)
# =====================================================================================
with tab_devices:
    site_by_label, site_labels = _site_options()
    filter_label = st.selectbox("Filter by site", ["All sites"] + site_labels, key="device_site_filter")
    filter_site_id = None if filter_label == "All sites" else site_by_label[filter_label]["site_id"]

    try:
        battery_profiles = list_battery_profiles(token).get("battery_profiles", [])
    except ApiError as e:
        battery_profiles = []
        st.error(f"Could not load battery profiles: {e.detail}")

    st.markdown("### Gateways")
    try:
        gateways = list_gateways(token, site_id=filter_site_id).get("gateways", [])
    except ApiError as e:
        gateways = []
        st.error(f"Could not load gateways: {e.detail}")

    if gateways:
        for gw in gateways:
            c1, c2, c3, c4, c5, c6, c7 = st.columns([3, 2, 2, 1, 1, 1, 1])
            with c1:
                st.write(f"**{gw['name'] or gw['gateway_id']}**")
                st.caption(f"ID: {gw['gateway_id']}")
            with c2:
                st.write(f"Site #{gw['site_id']}" if gw["site_id"] else "No site")
            with c3:
                st.markdown(badge("Active", "ok") if gw["is_active"] else badge("Inactive", "muted"), unsafe_allow_html=True)
            with c4:
                if st.button("Deactivate", key=f"deact_gw_{gw['gateway_id']}", disabled=in_support_view or not gw["is_active"]):
                    try:
                        soft_delete_gateway(token, gw["gateway_id"])
                        st.rerun()
                    except ApiError as e:
                        st.error(f"Could not deactivate: {e.detail}")
            with c5:
                _factory_reset_control(gw["serial_number"], in_support_view)
            with c6:
                _alert_rules_control(gw["serial_number"], in_support_view)
            with c7:
                _battery_control(gw["gateway_id"], True, gw.get("battery_profile_id"), battery_profiles, in_support_view)
    else:
        st.info("No gateways found for this filter.")

    st.markdown("---")
    st.markdown("### Sensors")
    try:
        sensors = list_sensors(token, site_id=filter_site_id).get("sensors", [])
    except ApiError as e:
        sensors = []
        st.error(f"Could not load sensors: {e.detail}")

    if sensors:
        for sn in sensors:
            c1, c2, c3, c4, c5, c6, c7 = st.columns([3, 2, 2, 1, 1, 1, 1])
            with c1:
                st.write(f"**{sn['name'] or sn['sensor_id']}**")
                st.caption(f"ID: {sn['sensor_id']} — Gateway: {sn['gateway_id']}")
            with c2:
                st.write(sn.get("location") or "—")
            with c3:
                st.markdown(badge("Active", "ok") if sn["is_active"] else badge("Inactive", "muted"), unsafe_allow_html=True)
            with c4:
                if st.button("Deactivate", key=f"deact_sn_{sn['sensor_id']}", disabled=in_support_view or not sn["is_active"]):
                    try:
                        soft_delete_sensor(token, sn["sensor_id"])
                        st.rerun()
                    except ApiError as e:
                        st.error(f"Could not deactivate: {e.detail}")
            with c5:
                _factory_reset_control(sn["serial_number"], in_support_view)
            with c6:
                _alert_rules_control(sn["serial_number"], in_support_view)
            with c7:
                _battery_control(sn["sensor_id"], False, sn.get("battery_profile_id"), battery_profiles, in_support_view)
    else:
        st.info("No sensors found for this filter.")

# =====================================================================================
# Provisioning
# =====================================================================================
with tab_provision:
    st.markdown("### Provision a Device")
    st.caption(
        "Enter the serial number printed on the device (or scanned from its QR code). "
        "We'll check whether it's available before activating it."
    )

    with st.form("check_device_form", border=False):
        serial = st.text_input("Serial number*", key="provision_serial")
        checked = st.form_submit_button("Check Serial", type="secondary", disabled=in_support_view)

    if checked and serial.strip():
        st.session_state.provision_check_result = None
        try:
            result = check_device(token, serial.strip())
            st.session_state.provision_check_result = result
            st.session_state.provision_check_serial = serial.strip()
        except ApiError as e:
            st.error(f"Could not check device: {e.detail}")

    result = st.session_state.get("provision_check_result")
    if result and st.session_state.get("provision_check_serial") == st.session_state.get("provision_serial", st.session_state.get("provision_check_serial")):
        status = result.get("status")
        if status == "not_found":
            st.error("This serial number isn't in the device registry — check it's correct, or contact WatchDog support.")
        elif status == "available":
            st.success(f"Available to provision — device type: **{result['device_type']}**")

            site_by_label, site_labels = _site_options()
            try:
                templates = list_node_templates(token).get("node_templates", [])
            except ApiError:
                templates = []
            template_by_label = {f"{t['name']} ({t['device_type']})": t for t in templates
                                  if t["device_type"] == result["device_type"]}

            with st.form("activate_device_form", border=False):
                if not site_labels:
                    st.warning("No sites available — create a site first.")
                site_label = st.selectbox("Site*", site_labels, key="activate_site") if site_labels else None
                name = st.text_input("Display name")
                location = st.text_input("Location") if result["device_type"] == "sensor" else None
                template_label = st.selectbox(
                    "Node template (optional — seeds alert rules)",
                    ["None"] + list(template_by_label.keys()), key="activate_template",
                )
                activate = st.form_submit_button("Activate Device", type="primary",
                                                   disabled=in_support_view or not site_labels)

            if activate:
                site_id = site_by_label[site_label]["site_id"]
                node_template_id = None if template_label == "None" else template_by_label[template_label]["node_template_id"]
                try:
                    activate_device(
                        token, st.session_state.provision_check_serial, site_id,
                        name=name or None, location=location or None, node_template_id=node_template_id,
                    )
                    st.success(f"Device {st.session_state.provision_check_serial} provisioned!")
                    st.session_state.provision_check_result = None
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not activate device: {e.detail}")
        elif status == "already_provisioned":
            if result.get("same_org"):
                st.warning("Already provisioned in your organisation. Deprovision it first if you want to re-provision.")
                if st.button("Deprovision this device", disabled=in_support_view):
                    try:
                        deprovision_device(token, st.session_state.provision_check_serial)
                        st.success("Device deprovisioned.")
                        st.session_state.provision_check_result = None
                        st.rerun()
                    except ApiError as e:
                        st.error(f"Could not deprovision: {e.detail}")
            else:
                st.error(
                    "This device is already provisioned to a **different organisation**. "
                    "If you didn't expect that, this may indicate the device was lost, stolen, "
                    "or resold without being deprovisioned — contact WatchDog support."
                )

# =====================================================================================
# Node Templates
# =====================================================================================
with tab_templates:
    st.markdown("### Node Templates")
    st.caption("Reusable configuration profiles applied to devices at provisioning time.")
    try:
        templates = list_node_templates(token).get("node_templates", [])
    except ApiError as e:
        templates = []
        st.error(f"Could not load node templates: {e.detail}")

    try:
        template_battery_profiles = list_battery_profiles(token).get("battery_profiles", [])
    except ApiError:
        template_battery_profiles = []

    if templates:
        for t in templates:
            c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 1, 1])
            with c1:
                st.write(f"**{t['name']}**")
            with c2:
                st.write(t["device_type"])
            with c3:
                st.caption(_label_for_battery_profile(template_battery_profiles, t.get("battery_profile_id")))
            with c4:
                if st.button("Delete", key=f"del_nt_{t['node_template_id']}", disabled=in_support_view):
                    try:
                        delete_node_template(token, t["node_template_id"])
                        st.rerun()
                    except ApiError as e:
                        st.error(f"Could not delete: {e.detail}")
            with c5:
                _module_pins_control(t, in_support_view)
    else:
        st.info("No node templates yet.")

    with st.expander("Add a new node template"):
        try:
            mcu_variants = list_mcu_variants(token).get("mcu_variants", [])
        except ApiError as e:
            mcu_variants = []
            st.error(f"Could not load MCU variants: {e.detail}")
        try:
            alert_templates = list_alert_templates(token).get("alert_templates", [])
        except ApiError:
            alert_templates = []

        if not mcu_variants:
            st.warning("No MCU variants exist yet — a WatchDog platform admin needs to add one first.")
        else:
            with st.form("create_node_template_form", border=False):
                name = st.text_input("Template name*")
                device_type = st.selectbox("Device type*", ["gateway", "sensor"])
                mcu_by_label = {m["name"]: m for m in mcu_variants}
                mcu_label = st.selectbox("MCU variant*", list(mcu_by_label.keys()))
                alert_by_label = {a["name"]: a for a in alert_templates}
                alert_label = st.selectbox("Alert template (optional)", ["None"] + list(alert_by_label.keys()))
                battery_by_label, battery_labels = _battery_profile_options(template_battery_profiles)
                battery_label = st.selectbox(
                    "Default battery type (optional — devices provisioned from this template start with this, can be changed per-device)",
                    battery_labels,
                )
                cloud_url = st.text_input("Cloud service URL (gateway only)") if device_type == "gateway" else None
                submitted = st.form_submit_button("Create Template", type="primary", disabled=in_support_view)

            if submitted:
                if not name.strip():
                    st.error("Template name is required.")
                else:
                    try:
                        create_node_template(
                            token, name=name, device_type=device_type,
                            mcu_variant_id=mcu_by_label[mcu_label]["mcu_variant_id"],
                            cloud_service_url=(cloud_url or None) if device_type == "gateway" else None,
                            alert_template_id=None if alert_label == "None" else alert_by_label[alert_label]["alert_template_id"],
                            battery_profile_id=battery_by_label[battery_label],
                        )
                        st.success(f"Template '{name}' created.")
                        st.rerun()
                    except ApiError as e:
                        st.error(f"Could not create template: {e.detail}")

# =====================================================================================
# Alert Templates (org-wide, applied to Node Templates at provisioning time)
# =====================================================================================
with tab_alert_templates:
    st.markdown("### Alert Templates")
    st.caption(
        "Templates are seeded onto a device's alert rules automatically when it's "
        "provisioned via a Node Template that references one. Editing a template here "
        "does not retroactively change rules already seeded onto existing devices — "
        "manage those directly from the device's own Alert Rules control in the Devices tab."
    )
    try:
        alert_templates = list_alert_templates(token).get("alert_templates", [])
    except ApiError as e:
        alert_templates = []
        st.error(f"Could not load alert templates: {e.detail}")

    with st.form("create_alert_template_form", border=False):
        new_template_name = st.text_input("New template name")
        create_submitted = st.form_submit_button("Create Template", type="primary", disabled=in_support_view)
    if create_submitted:
        if not new_template_name.strip():
            st.error("Template name is required.")
        else:
            try:
                create_alert_template(token, new_template_name)
                st.success(f"Template '{new_template_name}' created.")
                st.rerun()
            except ApiError as e:
                st.error(f"Could not create template: {e.detail}")

    st.markdown("---")

    if not alert_templates:
        st.info("No alert templates yet.")
    else:
        for tmpl in alert_templates:
            with st.expander(f"{tmpl['name']} — {len(tmpl['rules'])} rule(s)"):
                if tmpl["rules"]:
                    for r in tmpl["rules"]:
                        rc1, rc2, rc3 = st.columns([2, 3, 1])
                        with rc1:
                            st.write(f"**{r['metric_name']}**")
                        with rc2:
                            if r["metric_name"] == "motion":
                                st.write(f"Trigger: {r['trigger_value']}")
                            else:
                                st.write(f"Min: {r['threshold_min']}, Max: {r['threshold_max']}")
                        with rc3:
                            if st.button(
                                "Delete", key=f"del_tmpl_rule_{tmpl['alert_template_id']}_{r['alert_template_rule_id']}",
                                disabled=in_support_view,
                            ):
                                try:
                                    delete_alert_template_rule(token, tmpl["alert_template_id"], r["alert_template_rule_id"])
                                    st.rerun()
                                except ApiError as e:
                                    st.error(f"Could not delete rule: {e.detail}")
                else:
                    st.caption("No rules in this template yet.")

                st.markdown("**Add rule**")
                key_prefix = f"tmpl_{tmpl['alert_template_id']}"
                metric_name, threshold_min, threshold_max, trigger_value = _metric_threshold_inputs(key_prefix)
                if st.button("Save Rule", key=f"{key_prefix}_save", disabled=in_support_view):
                    try:
                        add_alert_template_rule(
                            token, tmpl["alert_template_id"], metric_name,
                            threshold_min=threshold_min, threshold_max=threshold_max, trigger_value=trigger_value,
                        )
                        st.success("Rule saved.")
                        st.rerun()
                    except ApiError as e:
                        st.error(f"Could not save rule: {e.detail}")

                st.markdown("---")
                if st.button("Delete Template", key=f"del_tmpl_{tmpl['alert_template_id']}", disabled=in_support_view):
                    try:
                        delete_alert_template(token, tmpl["alert_template_id"])
                        st.success(f"Template '{tmpl['name']}' deleted.")
                        st.rerun()
                    except ApiError as e:
                        st.error(f"Could not delete template: {e.detail}")