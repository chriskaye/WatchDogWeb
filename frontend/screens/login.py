import streamlit as st
from api_client import login, get_me, get_my_roles, ApiError

st.title("Log In")

email = st.session_state.get("login_email", "")
password = st.session_state.get("login_password", "")

if not email or not password:
    st.warning("No login details found. Please go back and enter your credentials.")
    if st.button("Back"):
        st.switch_page("screens/landing.py")
    st.stop()

with st.spinner("Signing in..."):
    try:
        token_data = login(email, password)
        access_token = token_data["access_token"]
        user = get_me(access_token)
        roles = get_my_roles(access_token)

        st.session_state.access_token = access_token
        st.session_state.user = user
        st.session_state.roles = roles
        st.session_state.logged_in = True
        st.session_state.mode = None
        del st.session_state["login_email"]
        del st.session_state["login_password"]

    except ApiError as e:
        if e.status_code == 403:
            st.error("Your email hasn't been verified yet. Check your inbox for the verification link.")
        else:
            st.error(f"Log in failed: {e.detail}")
        if st.button("Back"):
            st.switch_page("screens/landing.py")
        st.stop()
    except Exception:
        st.error("Could not reach the WatchDog server. Please try again shortly.")
        if st.button("Back"):
            st.switch_page("screens/landing.py")
        st.stop()

st.rerun()  # rebuilds navigation now that logged_in=True, lands on Dashboard