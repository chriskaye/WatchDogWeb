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
    pg = st.navigation(pages)
else:
    # position="hidden" removes the sidebar nav entirely — landing/login/create
    # account are only reachable via st.switch_page, never by direct URL click
    pg = st.navigation([landing_page, login_page, create_account_page], position="hidden")

pg.run()