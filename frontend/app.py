import streamlit as st
from session import init_session_state
from style import inject_css

st.set_page_config(page_title="WatchDog", page_icon="assets/favicon.ico", layout="wide")

init_session_state()
inject_css()

# ---------- LOGGED-OUT NAVIGATION ----------
landing_page = st.Page("screens/landing.py", title="WatchDog", default=True)
login_page = st.Page("screens/login.py", title="Log In")
create_account_page = st.Page("screens/create_account.py", title="Create Account")
about_page = st.Page("screens/about.py", title="About")

# ---------- EMAIL-LINK CONFIRMATION PAGES ----------
# Registered with explicit url_path so these resolve to a real page instead of falling
# through to Streamlit's own "Page not found" dialog. main.py's send_templated_email()
# links point at FRONTEND_BASE_URL + these exact paths (e.g. "/verify?token=..."), so the
# url_path values below must match main.py exactly if either side ever changes.
verify_page = st.Page("screens/verify.py", title="Verify Email", url_path="verify")
set_password_page = st.Page("screens/set_password.py", title="Set Password", url_path="set-password")
unlock_page = st.Page("screens/unlock.py", title="Unlock Account", url_path="unlock")
confirm_delete_page = st.Page("screens/confirm_delete.py", title="Confirm Deletion", url_path="confirm-delete")
gdpr_cancel_page = st.Page("screens/gdpr_cancel.py", title="Cancel Org Deletion", url_path="gdpr-cancel")
link_pages = [verify_page, set_password_page, unlock_page, confirm_delete_page, gdpr_cancel_page]

# ---------- LOGGED-IN NAVIGATION ----------
dashboard_page = st.Page("screens/dashboard.py", title="Dashboard", default=True)
configuration_page = st.Page("screens/configuration.py", title="Configuration")
reports_page = st.Page("screens/reports.py", title="Reports")
users_page = st.Page("screens/users.py", title="Users & Groups")
settings_page = st.Page("screens/settings.py", title="Settings")
admin_portal_page = st.Page("screens/admin_portal.py", title="WatchDog Admin Portal")
about_page = st.Page("screens/about.py", title="About")

if st.session_state.logged_in:
    pages = [dashboard_page, configuration_page, reports_page, users_page, settings_page]
    # Platform admin is a flat users.is_watchdog_admin flag, structurally separate from
    # org-level roles — see role model notes in the outstanding tasks doc. Only show the
    # catalog/support-staff portal to accounts that actually hold it.
    if (st.session_state.roles or {}).get("is_watchdog_admin"):
        pages.append(admin_portal_page)
    # link_pages deliberately NOT included here. Streamlit has no per-page "routable but
    # hidden from sidebar" flag — an earlier attempt grouped them into their own dict
    # section, but that section still rendered fully expanded in the visible sidebar for
    # every logged-in user (the bug that got reported and manually worked around by
    # emptying link_pages entirely, which also broke routing for the logged-out case —
    # restored below). position="hidden" is the only way to hide a nav call's sidebar and
    # it's all-or-nothing for that call, so there's no way to have these routable AND
    # hidden while pages/admin_portal_page stay visible in the same st.navigation() call.
    # Trade-off accepted: an email link clicked from an already-logged-in tab (rare — the
    # common case is a fresh, logged-out browser tab from an email client) will 404 rather
    # than route. Not a regression from before this feature existed.
    pg = st.navigation(pages)
else:
    # position="hidden" removes the sidebar nav entirely for every page in this list —
    # landing/login/create-account/link-confirmation pages are only reachable via
    # st.switch_page or a direct URL (email link), never by clicking a visible nav item.
    # This is the realistic case for every email-link click, so link_pages route
    # correctly here without ever appearing in a sidebar.
    pg = st.navigation([landing_page, login_page, create_account_page] + link_pages, position="hidden")

pg.run()