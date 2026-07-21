import streamlit as st
from session import do_logout, get_active_token
from style import inject_css, badge
from api_client import (
    ApiError,
    list_org_users, invite_user, suspend_user, unsuspend_user, lock_user, admin_delete_user,
    list_sites,
)

st.set_page_config(page_title="Users & Groups", page_icon="favicon.ico", layout="wide")
inject_css()

if st.session_state.get("logged_in"):
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=do_logout)

token = get_active_token()
in_support_view = st.session_state.get("support_session") is not None
my_user_id = (st.session_state.get("user") or {}).get("user_id")

st.markdown("## Users & Groups")
if in_support_view:
    st.warning(
        f"Viewing **{st.session_state.support_session['target_email']}**'s organisation in "
        "read-only Support Access mode. User management is disabled."
    )

try:
    users = list_org_users(token).get("users", [])
except ApiError as e:
    users = []
    st.error(f"Could not load the user roster: {e.detail}")

st.markdown("### Roster")
if not users:
    st.info("No users visible to you yet.")
else:
    for u in users:
        c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
        with c1:
            st.write(f"**{u['email']}**" + (" (you)" if u["user_id"] == my_user_id else ""))
            roles_text = u["global_role"] or ", ".join(f"{sr['role']}@site{sr['site_id']}" for sr in u["site_roles"]) or "no role"
            st.caption(roles_text)
        with c2:
            badges = []
            badges.append(badge("Verified", "ok") if u["is_verified"] else badge("Unverified", "muted"))
            st.markdown(" ".join(badges), unsafe_allow_html=True)
        with c3:
            badges = []
            if u["is_locked"]:
                badges.append(badge("Locked", "danger"))
            if u["is_suspended"]:
                badges.append(badge("Suspended", "warn"))
            if not u["is_locked"] and not u["is_suspended"]:
                badges.append(badge("Active", "ok"))
            st.markdown(" ".join(badges), unsafe_allow_html=True)
        with c4:
            is_self = u["user_id"] == my_user_id
            b1, b2, b3 = st.columns(3)
            with b1:
                if u["is_suspended"]:
                    if st.button("Unsuspend", key=f"unsusp_{u['user_id']}", disabled=in_support_view):
                        try:
                            unsuspend_user(token, u["user_id"]); st.rerun()
                        except ApiError as e:
                            st.error(f"Could not unsuspend: {e.detail}")
                else:
                    if st.button("Suspend", key=f"susp_{u['user_id']}", disabled=in_support_view or is_self):
                        try:
                            suspend_user(token, u["user_id"]); st.rerun()
                        except ApiError as e:
                            st.error(f"Could not suspend: {e.detail}")
            with b2:
                if st.button("Lock", key=f"lock_{u['user_id']}", disabled=in_support_view or is_self or u["is_locked"]):
                    try:
                        lock_user(token, u["user_id"]); st.rerun()
                    except ApiError as e:
                        st.error(f"Could not lock: {e.detail}")
            with b3:
                if st.button("Delete", key=f"del_{u['user_id']}", disabled=in_support_view or is_self):
                    st.session_state[f"confirm_delete_{u['user_id']}"] = True
            if st.session_state.get(f"confirm_delete_{u['user_id']}"):
                st.warning(f"Delete {u['email']}? This is permanent (GDPR erasure).")
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("Confirm Delete", key=f"confirm_del_{u['user_id']}", type="primary"):
                        try:
                            admin_delete_user(token, u["user_id"])
                            st.session_state.pop(f"confirm_delete_{u['user_id']}", None)
                            st.rerun()
                        except ApiError as e:
                            st.error(f"Could not delete: {e.detail}")
                with cc2:
                    if st.button("Cancel", key=f"cancel_del_{u['user_id']}"):
                        st.session_state.pop(f"confirm_delete_{u['user_id']}", None)
                        st.rerun()
        st.markdown("---")

st.markdown("### Invite a User")
try:
    sites = list_sites(token).get("sites", [])
except ApiError:
    sites = []
site_by_label = {f"{s['name']} (#{s['site_id']})": s for s in sites}

with st.form("invite_user_form", border=False):
    c1, c2 = st.columns(2)
    with c1:
        email = st.text_input("Email*")
        role = st.selectbox("Role*", ["site_viewer", "site_admin", "global_viewer", "global_admin"])
    with c2:
        is_global = role in ("global_admin", "global_viewer")
        site_label = None if is_global else st.selectbox(
            "Site*", list(site_by_label.keys()) if site_by_label else ["No sites available"],
        )
        initial_password = st.text_input("Preset password (optional)", type="password")
        grant_watchdog_admin = False
        if st.session_state.get("roles", {}).get("is_watchdog_admin"):
            grant_watchdog_admin = st.checkbox("Also grant WatchDog platform admin")
    submitted = st.form_submit_button("Send Invite", type="primary", disabled=in_support_view)

if submitted:
    if not email.strip():
        st.error("Email is required.")
    elif not is_global and not site_by_label:
        st.error("No sites exist yet — create one in Configuration first.")
    elif initial_password and len(initial_password) < 8:
        st.error("Preset password must be at least 8 characters.")
    else:
        site_id = None if is_global else site_by_label[site_label]["site_id"]
        try:
            invite_user(
                token, email.strip(), role, site_id=site_id,
                initial_password=initial_password or None,
                grant_watchdog_admin=grant_watchdog_admin,
            )
            st.success(f"Invited {email}.")
            st.rerun()
        except ApiError as e:
            st.error(f"Could not invite: {e.detail}")
