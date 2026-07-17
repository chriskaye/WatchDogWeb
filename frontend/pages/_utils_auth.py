import streamlit as st

def require_auth():
    if not st.session_state.get("auth", {}).get("is_authenticated", False):
        st.warning("You must be logged in to view this page.")
        st.switch_page("pages/2_Login.py")
        st.stop()
