import streamlit as st
from session import do_logout, get_active_token
from style import inject_css, badge
from api_client import (
    ApiError,
    list_auth_methods, unlink_auth_method,
    request_initial_password_setup,
    change_password,
    list_sites, set_default_site,
    enable_support_access, revoke_support_access, get_support_access_status,
    request_self_delete,
    request_org_deletion,
    create_backup, restore_backup, list_backups, update_backup_settings,
)
# NOTE: confirm_self_delete/cancel_org_deletion are consumed by email-link confirmation
# pages, not this screen — those need dedicated ?token= handlers (see landing.py's
# verify-email handling for the pattern) once routing for confirm-delete/set-password/
# unlock links is built out. Tracked in watchdogweb_outstanding_tasks.md.

st.set_page_config(page_title="Settings", page_icon="favicon.ico", layout="wide")
inject_css()

if st.session_state.get("logged_in"):
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=do_logout)

user = st.session_state.get("user") or {}
roles = st.session_state.get("roles") or {}
token = get_active_token()
in_support_view = st.session_state.get("support_session") is not None
is_global_admin = roles.get("global_role") == "global_admin"

st.markdown("## Settings")

if in_support_view:
    st.warning(
        f"You're viewing **{st.session_state.support_session['target_email']}**'s account "
        "in read-only Support Access mode. Account changes below are disabled."
    )

tab_names = ["Profile", "Appearance", "Login & Security"]
if is_global_admin:
    tab_names.append("Backups")
tab_names.append("Danger Zone")
tabs = st.tabs(tab_names)
tab_profile, tab_theme, tab_security = tabs[0], tabs[1], tabs[2]
if is_global_admin:
    tab_backups = tabs[3]
    tab_danger = tabs[4]
else:
    tab_backups = None
    tab_danger = tabs[3]

# =====================================================================================
# Profile
# =====================================================================================
with tab_profile:
    st.markdown("### Your Account")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Email", value=user.get("email", ""), disabled=True)
    with col2:
        st.text_input("Global role", value=roles.get("global_role") or "— (site-scoped only)", disabled=True)

    if roles.get("is_watchdog_admin"):
        st.markdown(badge("WatchDog Platform Admin", "ok"), unsafe_allow_html=True)

    site_roles = roles.get("site_roles") or []
    if site_roles:
        st.markdown("#### Site roles")
        for sr in site_roles:
            st.markdown(f"- Site `{sr['site_id']}` — **{sr['role']}**")

    st.markdown("---")
    st.markdown("### Default Site")
    st.caption(
        "Used to pre-select a site elsewhere in the app (e.g. as a delivery-address default "
        "in the future Shop). Purely a personal convenience — doesn't affect what you can see."
    )
    try:
        sites = list_sites(token).get("sites", [])
    except ApiError as e:
        sites = []
        st.error(f"Could not load sites: {e.detail}")

    if not sites:
        st.info("No sites yet — create one under Configuration → Sites first.")
    else:
        site_by_label = {f"{s['name']} (#{s['site_id']})": s["site_id"] for s in sites}
        labels = ["— None —"] + list(site_by_label.keys())
        current_default_id = user.get("default_site_id")
        current_label = next(
            (lbl for lbl, sid in site_by_label.items() if sid == current_default_id),
            "— None —",
        )
        chosen_label = st.selectbox(
            "Default site", labels, index=labels.index(current_label), key="default_site_select",
        )
        chosen_id = None if chosen_label == "— None —" else site_by_label[chosen_label]
        if st.button("Save Default Site", disabled=in_support_view or chosen_id == current_default_id):
            try:
                set_default_site(token, chosen_id)
                st.session_state.user["default_site_id"] = chosen_id
                st.success("Default site saved.")
                st.rerun()
            except ApiError as e:
                st.error(f"Could not save default site: {e.detail}")

# =====================================================================================
# Appearance
# =====================================================================================
with tab_theme:
    st.markdown("### Theme")
    st.caption("Applies for this session. A per-account saved preference isn't stored server-side yet.")
    current = st.session_state.get("theme", "watchdog")
    theme_choice = st.radio(
        "Theme", ["WatchDog", "Sensor Dog"],
        index=0 if current == "watchdog" else 1,
        horizontal=True,
    )
    new_theme = "watchdog" if theme_choice == "WatchDog" else "sensordog"
    if new_theme != current:
        st.session_state.theme = new_theme
        st.rerun()

    st.markdown("---")
    st.markdown("### Notifications")
    st.caption("UI-only for now — no notification-delivery endpoint exists in the API yet.")
    st.checkbox("Email alerts", value=True, key="notif_email")
    st.checkbox("Push alerts", value=False, key="notif_push")

# =====================================================================================
# Login & Security
# =====================================================================================
with tab_security:
    st.markdown("### Login Methods")
    try:
        methods = list_auth_methods(token).get("methods", [])
    except ApiError as e:
        methods = []
        st.error(f"Could not load login methods: {e.detail}")

    if not methods:
        st.info("No login methods found.")
    for m in methods:
        c1, c2 = st.columns([4, 1])
        with c1:
            label = "Password" if m["method_type"] == "password" else m["method_type"].capitalize()
            st.write(f"**{label}**" + (f" — `{m['provider_sub']}`" if m.get("provider_sub") else ""))
        with c2:
            disabled = in_support_view or len(methods) <= 1
            if st.button("Remove", key=f"unlink_{m['method_type']}", disabled=disabled):
                try:
                    unlink_auth_method(token, m["method_type"])
                    st.success(f"{label} removed.")
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not remove: {e.detail}")
    if methods and len(methods) <= 1:
        st.caption("You can't remove your only login method.")

    st.markdown("---")
    st.markdown("### Change Password")
    has_password_method = any(m["method_type"] == "password" for m in methods)
    if not has_password_method:
        st.caption(
            "You don't have a password login method yet — use **Forgot Password** from "
            "the login screen to set one."
        )
    else:
        st.caption(
            "Changing your password will sign you out of this session — you'll need to "
            "log back in afterwards."
        )
        with st.form("change_password_form", clear_on_submit=True):
            current_pw = st.text_input("Current password", type="password")
            new_pw = st.text_input("New password", type="password")
            new_pw_confirm = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Change Password", disabled=in_support_view)
        if submitted:
            if not current_pw or not new_pw:
                st.error("Both current and new password are required.")
            elif new_pw != new_pw_confirm:
                st.error("New password and confirmation don't match.")
            elif len(new_pw) < 8:
                st.error("New password must be at least 8 characters.")
            else:
                try:
                    change_password(token, current_pw, new_pw)
                    st.success("Password changed. Signing you out — please log back in.")
                    do_logout()
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not change password: {e.detail}")

    st.markdown("---")
    st.markdown("### Support Access")
    st.caption(
        "Opt in to let WatchDog support staff view (never edit) your organisation's data for "
        "24 hours, to help troubleshoot an issue."
    )
    try:
        status = get_support_access_status(token)
    except ApiError as e:
        status = None
        st.error(f"Could not load Support Access status: {e.detail}")

    if status and status.get("enabled"):
        st.markdown(badge("Active", "warn"), unsafe_allow_html=True)
        st.write(f"Expires: {status.get('expires_at', '—')}")
        if st.button("Revoke Support Access", disabled=in_support_view):
            try:
                revoke_support_access(token)
                st.success("Support Access revoked.")
                st.rerun()
            except ApiError as e:
                st.error(f"Could not revoke: {e.detail}")
    else:
        st.markdown(badge("Not active", "muted"), unsafe_allow_html=True)
        if st.button("Enable Support Access (24h)", disabled=in_support_view):
            try:
                enable_support_access(token)
                st.success("Support Access enabled for 24 hours.")
                st.rerun()
            except ApiError as e:
                st.error(f"Could not enable: {e.detail}")

# =====================================================================================
# Backups (Global Admin only — matches the API's own gate)
# =====================================================================================
if tab_backups is not None:
    with tab_backups:
        st.markdown("### Create Backup")
        with st.form("create_backup_form", clear_on_submit=True):
            backup_name = st.text_input("Name")
            backup_description = st.text_area("Description (optional)")
            create_submitted = st.form_submit_button("Create Backup", disabled=in_support_view)
        if create_submitted:
            if not backup_name:
                st.error("Name is required.")
            else:
                try:
                    create_backup(token, backup_name, backup_description or None)
                    st.success("Backup created.")
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not create backup: {e.detail}")

        st.markdown("---")
        st.markdown("### Existing Backups")
        try:
            backups = list_backups(token).get("backups", [])
        except ApiError as e:
            backups = []
            st.error(f"Could not load backups: {e.detail}")

        if not backups:
            st.info("No backups yet.")
        else:
            for b in backups:
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
                with c1:
                    st.write(f"**{b['name']}**")
                    if b.get("description"):
                        st.caption(b["description"])
                with c2:
                    st.write(f"{b['schedule_type']} — {b.get('created_at', '—')}")
                with c3:
                    status_kind = {"completed": "ok", "failed": "danger", "in_progress": "warn"}.get(b["status"], "muted")
                    st.markdown(badge(b["status"], status_kind), unsafe_allow_html=True)
                    if b.get("error_message"):
                        st.caption(b["error_message"])
                with c4:
                    if st.button("Restore", key=f"restore_{b['backup_id']}", disabled=in_support_view or b["status"] != "completed"):
                        st.session_state[f"confirm_restore_{b['backup_id']}"] = True
                if st.session_state.get(f"confirm_restore_{b['backup_id']}"):
                    st.warning(f"Restore **{b['name']}**? This overwrites current data for matching rows.")
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        if st.button("Confirm Restore", key=f"confirm_restore_btn_{b['backup_id']}"):
                            try:
                                restore_backup(token, b["backup_id"])
                                st.session_state[f"confirm_restore_{b['backup_id']}"] = False
                                st.success("Backup restored.")
                                st.rerun()
                            except ApiError as e:
                                st.error(f"Could not restore: {e.detail}")
                    with cc2:
                        if st.button("Cancel", key=f"cancel_restore_{b['backup_id']}"):
                            st.session_state[f"confirm_restore_{b['backup_id']}"] = False
                            st.rerun()

        st.markdown("---")
        st.markdown("### Backup Settings")
        st.caption(
            "There's no `GET` endpoint for backup settings yet, so this form can't show your "
            "org's current values — it only sets new ones. Flagging rather than silently "
            "showing stale/wrong defaults as if they were current."
        )
        with st.form("backup_settings_form"):
            is_enabled = st.checkbox("Automatic backups enabled")
            daily = st.number_input("Daily retention count", min_value=0, value=7)
            weekly = st.number_input("Weekly retention count", min_value=0, value=4)
            monthly = st.number_input("Monthly retention count", min_value=0, value=3)
            settings_submitted = st.form_submit_button("Save Backup Settings", disabled=in_support_view)
        if settings_submitted:
            try:
                update_backup_settings(
                    token, is_enabled=is_enabled, daily_retention_count=daily,
                    weekly_retention_count=weekly, monthly_retention_count=monthly,
                )
                st.success("Backup settings saved.")
            except ApiError as e:
                st.error(f"Could not save backup settings: {e.detail}")

# =====================================================================================
# Danger Zone
# =====================================================================================
with tab_danger:
    is_last_global_admin = roles.get("global_role") == "global_admin"

    st.markdown("### Delete Your Account")
    st.caption("Sends a confirmation link to your email. The link expires and must be confirmed to take effect.")
    if is_last_global_admin:
        st.warning(
            "You're the org's only Global Admin — you can't self-delete. "
            "Delete the whole organisation below instead, or promote another admin first."
        )
    else:
        if st.session_state.get("self_delete_requested"):
            st.info("Confirmation email sent. Check your inbox to finish deleting your account.")
        if st.button("Request Account Deletion", disabled=in_support_view):
            try:
                request_self_delete(token)
                st.session_state.self_delete_requested = True
                st.rerun()
            except ApiError as e:
                st.error(f"Could not request deletion: {e.detail}")

    if roles.get("global_role") == "global_admin":
        st.markdown("---")
        st.markdown("### Delete Organisation (GDPR)")
        st.caption(
            "Requests deletion of the entire organisation and all its data. Requires email "
            "confirmation and can be cancelled before it completes."
        )
        if st.button("Request Organisation Deletion", disabled=in_support_view):
            try:
                request_org_deletion(token)
                st.success("Organisation deletion requested — check your email to confirm.")
            except ApiError as e:
                st.error(f"Could not request deletion: {e.detail}")