import streamlit as st
from api_client import verify_email, ApiError

st.set_page_config(page_title="Verify Email", page_icon="favicon.ico")

token = st.query_params.get("token")
result_key = f"verify_result_{token}"

# Guard against re-firing the API call on every rerun (e.g. clicking the button below
# reruns this script before switch_page navigates away) — verification tokens are
# single-use, so a second call would just show a confusing "already used" error.
if token and result_key not in st.session_state:
    try:
        verify_email(token)
        st.session_state[result_key] = ("success", None)
    except ApiError as e:
        st.session_state[result_key] = ("error", e.detail)
    except Exception:
        st.session_state[result_key] = ("error", "Could not reach the WatchDog server. Please try again shortly.")

with st.container(horizontal_alignment="center"):
    st.title("WatchDog", text_alignment="center")
    st.markdown("---")

    if not token:
        st.error("No verification token found in the link. Please use the link from your email.")
    else:
        status, detail = st.session_state[result_key]
        if status == "success":
            st.success("Your email has been verified! You can now log in.")
        else:
            st.error(f"Verification failed: {detail}")

    if st.button("Continue to Log In"):
        st.session_state.mode = "login"
        st.switch_page("screens/landing.py")