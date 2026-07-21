import streamlit as st
from session import do_logout, get_active_token
from style import inject_css, badge
from api_client import (
    ApiError,
    list_auth_methods, unlink_auth_method,
    request_initial_password_setup,
    enable_support_access, revoke_support_access, get_support_access_status,
    request_self_delete,
    request_org_deletion,
)
# NOTE: confirm_self_delete/cancel_org_deletion are consumed by email-link confirmation
# pages, not this screen — those need dedicated ?token= handlers (see landing.py's
# verify-email handling for the pattern) once routing for confirm-delete/set-password/
# unlock links is built out. Tracked in _private/watchdogweb_outstanding_tasks.md.

st.set_page_config(page_title="Settings", page_icon="favicon.ico", layout="wide")
inject_css()

if st.session_state.get("logged_in"):
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=do_logout)

user = st.session_state.get("user") or {}
roles = st.session_state.get("roles") or {}
token = get_active_token()
in_support_view = st.session_state.get("support_session") is not None

st.markdown("## Settings")

if in_support_view:
    st.warning(
        f"You're viewing **{st.session_state.support_session['target_email']}**'s account "
        "in read-only Support Access mode. Account changes below are disabled."
    )

tab_profile, tab_theme, tab_security, tab_danger = st.tabs(
    ["Profile", "Appearance", "Login & Security", "Danger Zone"]
)

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
    st.markdown("### Password")
    st.caption(
        "There's currently no in-app 'change password' — the API only supports setting a "
        "password for an account that has none yet, or resetting one that's locked. If you "
        "need a new password, use **Forgot Password** from the login screen."
    )

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
