import streamlit as st
import requests

# Hide the whole sidebar
st.markdown("""
    <style>
        section[data-testid="stSidebar"] {
            display: none;
        }
    </style>
""", unsafe_allow_html=True)

if "auth" not in st.session_state:
    st.session_state.auth = {
        "is_authenticated": False,
        "username": None,
    }

st.set_page_config(page_title="Create Account [WatchDog]", page_icon="favicon.ico", layout="centered")

API_BASE = "http://localhost:8000"  # adjust to your FastAPI gateway


def signup(email, password):
    try:
        resp = requests.post(
            f"{API_BASE}/auth/register",
            json={"email": email, "password": password},
            timeout=5,
        )
        if resp.status_code == 201:
            return True, None
        else:
            return False, resp.text
    except Exception as e:
        return False, str(e)

if st.session_state.auth["is_authenticated"]:
    st.sidebar.title("Menu")
    st.sidebar.button("Log Out", on_click=lambda: st.session_state.auth.update({
        "is_authenticated": False,
        "user": None,
        "token": None,
    }))

signup_col = st.columns(1)

with signup_col:
    st.markdown("### Sign Up")
    signup_email = st.text_input("New Email", key="signup_email")
    signup_password = st.text_input("New Password", type="password", key="signup_password")
    if st.button("Create Account"):
        ok, err = signup(signup_email, signup_password)
        if ok:
            st.success("Account created. You can now log in.")
        else:
            st.error(f"Sign-up failed: {err}")
