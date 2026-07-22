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
# Included in both nav branches below: session_state.logged_in can legitimately be True
# when one of these is clicked (e.g. cancelling org deletion from an already-logged-in
# tab), even though the common case is a fresh, logged-out browser tab from an email client.
verify_page = st.Page("screens/verify.py", title="Verify Email", url_path="verify")
set_password_page = st.Page("screens/set_password.py", title="Set Password", url_path="set-password")
unlock_page = st.Page("screens/unlock.py", title="Unlock Account", url_path="unlock")
confirm_delete_page = st.Page("screens/confirm_delete.py", title="Confirm Deletion", url_path="confirm-delete")
gdpr_cancel_page = st.Page("screens/gdpr_cancel.py", title="Cancel Org Deletion", url_path="gdpr-cancel")
link_pages = [verify_page, set_password_page, unlock_page, confirm_delete_page, gdpr_cancel_page]

# ---------- LOGGED-IN NAVIGATION ----------
dashboard_page = st.Page("screens/dashboard.py", title="Dashboard", default=True)
configuration_page = st.Page("screens/configuration.py", title="Configuration")
users_page = st.Page("screens/users.py", title="Users & Groups")
settings_page = st.Page("screens/settings.py", title="Settings")
admin_portal_page = st.Page("screens/admin_portal.py", title="WatchDog Admin Portal")
about_page = st.Page("screens/about.py", title="About")

if st.session_state.logged_in:
    pages = [dashboard_page, configuration_page, users_page, settings_page]
    # Platform admin is a flat users.is_watchdog_admin flag, structurally separate from
    # org-level roles — see role model notes in the outstanding tasks doc. Only show the
    # catalog/support-staff portal to accounts that actually hold it.
    if (st.session_state.roles or {}).get("is_watchdog_admin"):
        pages.append(admin_portal_page)
    # link_pages tucked into their own sidebar section rather than mixed into the main
    # list — keeps them routable without cluttering everyday navigation.
    pg = st.navigation({"WatchDog": pages, "Account Links": link_pages})
else:
    # position="hidden" removes the sidebar nav entirely — landing/login/create
    # account/link-confirmation pages are only reachable via st.switch_page or a direct
    # URL (email link), never by clicking a visible nav item
    pg = st.navigation([landing_page, login_page, create_account_page] + link_pages, position="hidden")

pg.run()