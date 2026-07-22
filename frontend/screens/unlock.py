import streamlit as st
from api_client import confirm_unlock, ApiError

st.set_page_config(page_title="Unlock Account", page_icon="favicon.ico")

token = st.query_params.get("token")
done_key = f"unlock_done_{token}"

with st.container(horizontal_alignment="center"):
    st.title("WatchDog", text_alignment="center")
    st.markdown("---")
    st.subheader("Unlock Your Account")
    st.caption("Setting a new password also unlocks the account.")

    if not token:
        st.error("No token found in the link. Please use the link from your email.")
    elif st.session_state.get(done_key):
        st.success("Account unlocked! You can now log in with your new password.")
        if st.button("Continue to Log In"):
            st.session_state.mode = "login"
            st.switch_page("screens/landing.py")
    else:
        with st.form("unlock_form"):
            new_pw = st.text_input("New password", type="password")
            confirm_pw = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Unlock Account", type="primary")
        if submitted:
            if new_pw != confirm_pw:
                st.error("Passwords don't match.")
            elif len(new_pw) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                try:
                    confirm_unlock(token, new_pw)
                    st.session_state[done_key] = True
                    st.rerun()
                except ApiError as e:
                    st.error(f"Could not unlock account: {e.detail}")
                except Exception:
                    st.error("Could not reach the WatchDog server. Please try again shortly.")