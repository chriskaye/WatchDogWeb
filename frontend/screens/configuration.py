import streamlit as st
from session import do_logout

st.set_page_config(page_title="Configuration", page_icon="favicon.ico", layout="wide")

if st.session_state.get("logged_in"):
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=do_logout)

st.markdown("## Configuration")

st.info(
    "Device inventory and provisioning is being rebuilt against the real API "
    "(gateways, sensors, and node templates) — the previous version of this page "
    "was placeholder content not wired to anything. Coming shortly."
)