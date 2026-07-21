import streamlit as st
from session import do_logout, get_active_token, end_support_view
from style import inject_css, badge
from api_client import (
    ApiError,
    list_device_registry, create_device_registry_entry, update_device_registry_entry,
    delete_device_registry_entry, list_device_radios, add_device_radio, delete_device_radio,
    list_sensor_module_types, create_sensor_module_type, delete_sensor_module_type,
    list_mcu_variants, create_mcu_variant, list_gpio_pins, add_gpio_pin,
    list_module_compatibility, add_module_compatibility, delete_module_compatibility,
    list_support_grants, start_support_session, end_support_session,
)

st.set_page_config(page_title="WatchDog Admin Portal", page_icon="favicon.ico", layout="wide")
inject_css()

if st.session_state.get("logged_in"):
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=do_logout)

roles = st.session_state.get("roles") or {}
if not roles.get("is_watchdog_admin"):
    st.error("This page is only available to WatchDog platform admins.")
    st.stop()

token = get_active_token()
in_support_view = st.session_state.get("support_session") is not None

st.markdown("## WatchDog Admin Portal")
st.caption("Platform-level hardware catalog and support tooling — visible only to WatchDog platform admins.")
if in_support_view:
    st.warning("You're inside a Support Access session — end it below before making catalog changes here.")

tab_registry, tab_modules, tab_mcu, tab_compat, tab_support = st.tabs(
    ["Device Registry", "Sensor Modules", "MCU Variants & GPIO", "Module Compatibility", "Support Access"]
)

# =====================================================================================
# Device Registry
# =====================================================================================
with tab_registry:
    st.markdown("### Factory Device Registry")
    filter_choice = st.radio("Filter", ["All", "Unprovisioned", "Provisioned"], horizontal=True, key="dr_filter")
    is_provisioned = {"All": None, "Unprovisioned": False, "Provisioned": True}[filter_choice]
    try:
        devices = list_device_registry(token, is_provisioned=is_provisioned).get("devices", [])
    except ApiError as e:
        devices = []
        st.error(f"Could not load device registry: {e.detail}")

    if devices:
        st.dataframe(
            [{"Serial": d["serial_number"], "Type": d["device_type"], "Model": d.get("model") or "—",
              "Provisioned": "Yes" if d["is_provisioned"] else "No"} for d in devices],
            hide_index=True, width="stretch",
        )
        with st.expander("Manage a device / radios"):
            serials = {d["serial_number"]: d for d in devices}
            chosen = st.selectbox("Serial number", list(serials.keys()), key="dr_manage_select")
            device = serials[chosen]
            if device["is_provisioned"]:
                st.info("This device is already provisioned — factory specs are locked, and it can't be deleted from the registry until deprovisioned.")
            else:
                with st.form("update_device_form", border=False):
                    model = st.text_input("Model", value=device.get("model") or "")
                    flash_kb = st.number_input("Flash (KB)", min_value=0, value=0, step=1)
                    save = st.form_submit_button("Save", disabled=in_support_view)
                if save:
                    try:
                        update_device_registry_entry(token, chosen, model=model or None, flash_kb=flash_kb or None)
                        st.success("Updated."); st.rerun()
                    except ApiError as e:
                        st.error(f"Could not update: {e.detail}")
                if st.button("Delete from registry", key="dr_delete", disabled=in_support_view):
                    try:
                        delete_device_registry_entry(token, chosen)
                        st.success("Deleted."); st.rerun()
                    except ApiError as e:
                        st.error(f"Could not delete: {e.detail}")

            st.markdown("#### Radios")
            try:
                radios = list_device_radios(token, chosen).get("radios", [])
            except ApiError as e:
                radios = []
                st.error(f"Could not load radios: {e.detail}")
            for r in radios:
                rc1, rc2 = st.columns([4, 1])
                with rc1:
                    st.write(f"{r['radio_type']} — {r.get('mac_address') or 'no MAC recorded'}")
                with rc2:
                    if st.button("Remove", key=f"rm_radio_{r['device_radio_id']}", disabled=in_support_view):
                        try:
                            delete_device_radio(token, chosen, r["device_radio_id"]); st.rerun()
                        except ApiError as e:
                            st.error(f"Could not remove: {e.detail}")
            with st.form("add_radio_form", border=False):
                radio_type = st.text_input("Radio type (e.g. wifi, lora, ble)")
                mac = st.text_input("MAC address (optional)")
                add_radio = st.form_submit_button("Add Radio", disabled=in_support_view)
            if add_radio and radio_type.strip():
                try:
                    add_device_radio(token, chosen, radio_type=radio_type.strip(), mac_address=mac or None)
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not add radio: {e.detail}")
    else:
        st.info("No devices in the registry for this filter.")

    with st.expander("Register a new factory device"):
        try:
            mcu_variants = list_mcu_variants(token).get("mcu_variants", [])
        except ApiError:
            mcu_variants = []
        mcu_by_label = {m["name"]: m for m in mcu_variants}
        with st.form("create_device_form", border=False):
            serial_number = st.text_input("Serial number*")
            device_type = st.selectbox("Device type*", ["gateway", "sensor"])
            model = st.text_input("Model")
            mcu_label = st.selectbox("MCU variant", ["None"] + list(mcu_by_label.keys()))
            submitted = st.form_submit_button("Register Device", type="primary", disabled=in_support_view)
        if submitted:
            if not serial_number.strip():
                st.error("Serial number is required.")
            else:
                try:
                    create_device_registry_entry(
                        token, serial_number=serial_number.strip(), device_type=device_type,
                        model=model or None,
                        mcu_variant_id=None if mcu_label == "None" else mcu_by_label[mcu_label]["mcu_variant_id"],
                    )
                    st.success(f"Registered {serial_number}."); st.rerun()
                except ApiError as e:
                    st.error(f"Could not register: {e.detail}")

# =====================================================================================
# Sensor Module Types
# =====================================================================================
with tab_modules:
    st.markdown("### Sensor Module Types")
    try:
        module_types = list_sensor_module_types(token).get("module_types", [])
    except ApiError as e:
        module_types = []
        st.error(f"Could not load module types: {e.detail}")

    for m in module_types:
        c1, c2, c3 = st.columns([3, 3, 1])
        with c1:
            st.write(f"**{m['name']}**")
            st.caption(m["module_type"])
        with c2:
            st.write(m.get("communication_type") or "—")
        with c3:
            key = m["module_type_id"]
            if st.button("Delete", key=f"del_mod_{key}", disabled=in_support_view):
                try:
                    delete_sensor_module_type(token, key); st.rerun()
                except ApiError as e:
                    st.error(f"Could not delete: {e.detail}")
    if not module_types:
        st.info("No sensor module types defined yet.")

    with st.expander("Add a sensor module type"):
        with st.form("create_module_type_form", border=False):
            module_type = st.text_input("Module type code* (e.g. temp_humidity_v2)")
            name = st.text_input("Display name*")
            communication_type = st.text_input("Communication type (e.g. i2c, spi)")
            default_i2c_address = st.text_input("Default I2C address (optional)")
            submitted = st.form_submit_button("Create", type="primary", disabled=in_support_view)
        if submitted:
            if not module_type.strip() or not name.strip():
                st.error("Module type code and display name are required.")
            else:
                try:
                    create_sensor_module_type(
                        token, module_type.strip(), name.strip(),
                        communication_type=communication_type or None,
                        default_i2c_address=default_i2c_address or None,
                    )
                    st.success(f"Created {name}."); st.rerun()
                except ApiError as e:
                    st.error(f"Could not create: {e.detail}")

# =====================================================================================
# MCU Variants & GPIO
# =====================================================================================
with tab_mcu:
    st.markdown("### MCU Variants")
    try:
        mcu_variants = list_mcu_variants(token).get("mcu_variants", [])
    except ApiError as e:
        mcu_variants = []
        st.error(f"Could not load MCU variants: {e.detail}")

    with st.form("create_mcu_variant_form", border=False):
        name = st.text_input("New MCU variant name*")
        submitted = st.form_submit_button("Add Variant", disabled=in_support_view)
    if submitted and name.strip():
        try:
            create_mcu_variant(token, name.strip()); st.rerun()
        except ApiError as e:
            st.error(f"Could not add: {e.detail}")

    if mcu_variants:
        mcu_by_label = {m["name"]: m for m in mcu_variants}
        chosen_label = st.selectbox("View GPIO pins for", list(mcu_by_label.keys()), key="mcu_gpio_select")
        mcu = mcu_by_label[chosen_label]
        try:
            pins = list_gpio_pins(token, mcu["mcu_variant_id"]).get("gpio_pins", [])
        except ApiError as e:
            pins = []
            st.error(f"Could not load GPIO pins: {e.detail}")

        if pins:
            st.dataframe(
                [{"Pin": p["gpio_pin"], "Status": p["status"], "Notes": p.get("notes") or "—"} for p in pins],
                hide_index=True, width="stretch",
            )
        else:
            st.info("No GPIO pins recorded for this variant yet.")

        with st.form("add_gpio_pin_form", border=False):
            pin = st.text_input("Pin (e.g. GPIO4)")
            status = st.selectbox("Status", ["available", "reserved", "restricted"])
            notes = st.text_input("Notes")
            add_pin = st.form_submit_button("Add / Update Pin", disabled=in_support_view)
        if add_pin and pin.strip():
            try:
                add_gpio_pin(token, mcu["mcu_variant_id"], pin.strip(), status=status, notes=notes or None)
                st.rerun()
            except ApiError as e:
                st.error(f"Could not save pin: {e.detail}")
    else:
        st.info("No MCU variants yet — add one above.")

# =====================================================================================
# Module <-> MCU Compatibility
# =====================================================================================
with tab_compat:
    st.markdown("### Module / MCU Compatibility")
    try:
        mcu_variants = list_mcu_variants(token).get("mcu_variants", [])
    except ApiError:
        mcu_variants = []
    try:
        module_types = list_sensor_module_types(token).get("module_types", [])
    except ApiError:
        module_types = []

    if not mcu_variants or not module_types:
        st.info("Add at least one MCU variant and one sensor module type first.")
    else:
        mcu_by_label = {m["name"]: m for m in mcu_variants}
        mcu_label = st.selectbox("MCU variant", list(mcu_by_label.keys()), key="compat_mcu_select")
        mcu_id = mcu_by_label[mcu_label]["mcu_variant_id"]

        try:
            compat = list_module_compatibility(token, mcu_variant_id=mcu_id).get("compatibility", [])
        except ApiError as e:
            compat = []
            st.error(f"Could not load compatibility: {e.detail}")

        compatible_ids = {c["module_type_id"] for c in compat}
        for m in module_types:
            mid = m["module_type_id"]
            c1, c2 = st.columns([4, 1])
            with c1:
                st.write(m["name"])
            with c2:
                if mid in compatible_ids:
                    if st.button("Remove", key=f"rmcompat_{mid}", disabled=in_support_view):
                        try:
                            delete_module_compatibility(token, mid, mcu_id); st.rerun()
                        except ApiError as e:
                            st.error(f"Could not remove: {e.detail}")
                else:
                    if st.button("Mark compatible", key=f"addcompat_{mid}", disabled=in_support_view):
                        try:
                            add_module_compatibility(token, mid, mcu_id); st.rerun()
                        except ApiError as e:
                            st.error(f"Could not add: {e.detail}")

# =====================================================================================
# Support Access — WatchDog staff side
# =====================================================================================
with tab_support:
    st.markdown("### Active Support Access Grants")
    st.caption("Users who've opted in to let WatchDog staff view their org's data for 24h.")

    if st.session_state.get("support_session"):
        s = st.session_state.support_session
        st.success(f"Currently viewing **{s['target_email']}** in read-only mode.")
        if st.button("End Support Session"):
            end_support_view()
            st.rerun()
    else:
        try:
            grants = list_support_grants(token).get("grants", [])
        except ApiError as e:
            grants = []
            st.error(f"Could not load grants: {e.detail}")

        if grants:
            for g in grants:
                c1, c2, c3 = st.columns([3, 3, 2])
                with c1:
                    st.write(f"**{g['email']}**")
                with c2:
                    st.caption(f"Expires {g['expires_at']}")
                with c3:
                    if st.button("Start Session", key=f"start_sess_{g['grant_id']}"):
                        try:
                            resp = start_support_session(token, g["grant_id"])
                            st.session_state.support_session = {
                                "support_token": resp["support_token"],
                                "session_id": resp["session_id"],
                                "target_email": g["email"],
                                "expires_at": g["expires_at"],
                            }
                            st.rerun()
                        except ApiError as e:
                            st.error(f"Could not start session: {e.detail}")
        else:
            st.info("No active Support Access grants right now.")
