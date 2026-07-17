import streamlit as st

st.set_page_config(page_title="WatchDog", page_icon="assets/favicon.ico")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# ---------- LOGGED-OUT NAVIGATION ----------
landing_page = st.Page("screens/landing.py", title="WatchDog", default=True)
login_page = st.Page("screens/login.py", title="Log In")
create_account_page = st.Page("screens/create_account.py", title="Create Account")
about_page = st.Page("screens/about.py", title="About")

# ---------- LOGGED-IN NAVIGATION ----------
dashboard_page = st.Page("screens/dashboard.py", title="Dashboard", default=True)
configuration_page = st.Page("screens/configuration.py", title="Configuration")
settings_page = st.Page("screens/settings.py", title="Settings")
about_page = st.Page("screens/about.py", title="About")

if st.session_state.logged_in:
    pg = st.navigation([dashboard_page, configuration_page, settings_page, about_page])
else:
    # position="hidden" removes the sidebar nav entirely — landing/login/create
    # account are only reachable via st.switch_page, never by direct URL click
    #pg = st.navigation([landing_page, login_page, create_account_page], position="hidden")
    pg = st.navigation([landing_page, about_page])

pg.run()