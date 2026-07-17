import streamlit as st

st.set_page_config(page_title="Configuration", page_icon="favicon.ico", layout="wide")

if st.session_state.get("logged_in"):
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=lambda: st.session_state.auth.update({
        "is_authenticated": False,
        "user": None,
        "token": None,
    }))

st.markdown("## Configuration")

st.markdown("### Gateways")
st.text_input("Gateway URL", value="mqtt://broker.local:1883")
st.text_input("API Base URL", value="http://localhost:8000")

st.markdown("---")
st.markdown("### Sensor Provisioning")

sensor_name = st.text_input("Sensor Name")
sensor_type = st.selectbox("Sensor Type", ["Temperature", "Humidity", "Pressure", "Custom"])
if st.button("Register Sensor"):
    st.success(f"Sensor '{sensor_name}' registered as {sensor_type} (placeholder).")
