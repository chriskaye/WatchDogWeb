import streamlit as st
from session import do_logout

st.set_page_config(page_title="User Settings", page_icon="favicon.ico", layout="wide")

if st.session_state.get("logged_in"):
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=do_logout)

st.markdown("## User Settings")

st.markdown("### Theme")
theme_choice = st.radio("Theme", ["WatchDog", "Sensor Dog"])
st.session_state.theme = "watchdog" if theme_choice == "WatchDog" else "sensordog"

st.markdown("---")
st.markdown("### Notifications")
email_alerts = st.checkbox("Email alerts", value=True)
push_alerts = st.checkbox("Push alerts", value=False)

st.markdown("---")
st.markdown("### Account")
st.write(f"Current user: {st.session_state.user['email']}")
if st.button("Delete Account (placeholder)"):
    st.warning("Account deletion flow not implemented yet.")