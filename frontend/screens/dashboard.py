import streamlit as st
import requests
import pandas as pd
import numpy as np

st.set_page_config(page_title="Dashboard", page_icon="favicon.ico", layout="wide")

theme = st.session_state.get("theme", "watchdog")
accent = "#00e5ff" if theme == "watchdog" else "#ff9800"

if st.session_state.get("logged_in"):
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=lambda: st.session_state.auth.update({
        "is_authenticated": False,
        "user": None,
        "token": None,
    }))


st.markdown(f"## Dashboard ({'WatchDog' if theme == 'watchdog' else 'SensorDog'})")

# Example sensor summary cards
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown('<div class="card">Total Sensors<br><h3>42</h3></div>', unsafe_allow_html=True)
with c2:
    st.markdown('<div class="card">Active Alerts<br><h3>3</h3></div>', unsafe_allow_html=True)
with c3:
    st.markdown('<div class="card">Last Sync<br><h3>2 min ago</h3></div>', unsafe_allow_html=True)

st.markdown("---")
st.markdown("### Live Metrics")

# Placeholder chart
data = pd.DataFrame(
    {
        "time": pd.date_range("2026-07-16", periods=20, freq="T"),
        "value": np.random.randn(20).cumsum(),
    }
)
st.line_chart(data.set_index("time"))
