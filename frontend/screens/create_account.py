import streamlit as st
from api_client import register, ApiError

st.title("Create Account")

email = st.session_state.get("new_email", "")
password = st.session_state.get("new_password", "")
confirm = st.session_state.get("new_confirm", "")

if not email or not password:
    st.warning("No account details found. Please go back and fill in the form.")
    if st.button("Back"):
        st.switch_page("screens/landing.py")
    st.stop()

if password != confirm:
    st.error("Passwords do not match.")
    if st.button("Back"):
        st.switch_page("screens/landing.py")
    st.stop()

if len(password) < 8:
    st.error("Password must be at least 8 characters.")
    if st.button("Back"):
        st.switch_page("screens/landing.py")
    st.stop()

with st.spinner("Creating your account..."):
    try:
        result = register(email, password)
        for key in ("new_email", "new_password", "new_confirm"):
            st.session_state.pop(key, None)
    except ApiError as e:
        st.error(f"Could not create account: {e.detail}")
        if st.button("Back"):
            st.switch_page("screens/landing.py")
        st.stop()
    except Exception:
        st.error("Could not reach the WatchDog server. Please try again shortly.")
        if st.button("Back"):
            st.switch_page("screens/landing.py")
        st.stop()

st.success(f"Account created for {result['email']}!")
st.info("Check your inbox for a verification link — it expires in 24 hours.")

if st.button("Back to Log In"):
    st.session_state.mode = "login"
    st.switch_page("screens/landing.py")