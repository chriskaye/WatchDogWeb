import streamlit as st
from api_client import set_password, ApiError

st.set_page_config(page_title="Set Password", page_icon="favicon.ico")

token = st.query_params.get("token")
done_key = f"password_set_{token}"

with st.container(horizontal_alignment="center"):
    st.title("WatchDog", text_alignment="center")
    st.markdown("---")
    st.subheader("Set Your Password")

    if not token:
        st.error("No token found in the link. Please use the link from your email.")
    elif st.session_state.get(done_key):
        st.success("Password set! You can now log in.")
        if st.button("Continue to Log In"):
            st.session_state.mode = "login"
            st.switch_page("screens/landing.py")
    else:
        with st.form("set_password_form"):
            new_pw = st.text_input("New password", type="password")
            confirm_pw = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Set Password", type="primary")
        if submitted:
            if new_pw != confirm_pw:
                st.error("Passwords don't match.")
            elif len(new_pw) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                try:
                    set_password(token, new_pw)
                    st.session_state[done_key] = True
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not set password: {e.detail}")
                except Exception:
                    st.error("Could not reach the WatchDog server. Please try again shortly.")