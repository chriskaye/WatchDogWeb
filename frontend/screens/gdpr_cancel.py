import streamlit as st
from api_client import login, get_me, get_my_roles, cancel_org_deletion, ApiError

st.set_page_config(page_title="Cancel Organisation Deletion", page_icon="favicon.ico")

token = st.query_params.get("token")
done_key = f"gdpr_cancelled_{token}"

with st.container(horizontal_alignment="center"):
    st.title("WatchDog", text_alignment="center")
    st.markdown("---")
    st.subheader("Cancel Organisation Deletion")

    if not token:
        st.error("No token found in the link. Please use the link from your email.")
    elif st.session_state.get(done_key):
        st.success("Organisation deletion has been cancelled.")
        if st.button("Go to Dashboard"):
            st.switch_page("screens/dashboard.py")
    elif not st.session_state.get("logged_in"):
        # POST /organisations/gdpr_delete/cancel requires an authenticated Global Admin —
        # unlike the other confirmation links, a bare token isn't enough. Handle that here
        # rather than bouncing the user through a separate login page and losing the token.
        st.info("Log in as a Global Admin of the affected organisation to cancel the deletion.")
        with st.form("gdpr_cancel_login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log In", type="primary")
        if submitted:
            try:
                token_data = login(email, password)
                access_token = token_data["access_token"]
                st.session_state.access_token = access_token
                st.session_state.user = get_me(access_token)
                st.session_state.roles = get_my_roles(access_token)
                st.session_state.logged_in = True
                st.rerun()
            except ApiError as e:
                st.error(f"Log in failed: {e.detail}")
            except Exception:
                st.error("Could not reach the WatchDog server. Please try again shortly.")
    else:
        try:
            cancel_org_deletion(st.session_state.access_token, token)
            st.session_state[done_key] = True
            st.rerun()
        except ApiError as e:
            st.error(f"Could not cancel deletion: {e.detail}")
            if st.button("Go to Dashboard"):
                st.switch_page("screens/dashboard.py")
        except Exception:
            st.error("Could not reach the WatchDog server. Please try again shortly.")