import streamlit as st
import requests

API_BASE = "http://localhost:8000"  # adjust to your FastAPI gateway

# Hide the whole sidebar
st.markdown("""
    <style>
        section[data-testid="stSidebar"] {
            display: none;
        }
    </style>
""", unsafe_allow_html=True)

st.set_page_config(page_title="Login [WatchDog]", page_icon="favicon.ico", layout="centered")

st.title("Processing Login")

email = st.session_state.get("login_email")
password = st.session_state.get("login_password")

if not email or not password:
    st.error("No login data received.")
    st.stop()

# Your login logic here
st.write(f"Logging in user: {email}")



if st.session_state.auth["is_authenticated"]:
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=lambda: st.session_state.auth.update({
        "is_authenticated": False,
        "user": None,
        "token": None,
    }))

st.markdown("## Log In")
login_email = st.text_input("Email", key="login_email")
login_password = st.text_input("Password", type="password", key="login_password")

#login_col = st.columns(1)

#with login_col:
if st.button("Log In"):
    ok, err = login(login_email, login_password)
    if ok:
        st.success("Logged in successfully.")
        st.switch_page("pages/1_Dashboard.py")
    else:
        st.error(f"Login failed: {err}")
