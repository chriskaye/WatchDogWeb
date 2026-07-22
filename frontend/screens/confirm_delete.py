import streamlit as st
from api_client import confirm_self_delete, ApiError

st.set_page_config(page_title="Confirm Account Deletion", page_icon="favicon.ico")

token = st.query_params.get("token")
done_key = f"delete_confirmed_{token}"

with st.container(horizontal_alignment="center"):
    st.title("WatchDog", text_alignment="center")
    st.markdown("---")
    st.subheader("Confirm Account Deletion")

    if not token:
        st.error("No token found in the link. Please use the link from your email.")
    elif st.session_state.get(done_key):
        st.success("Your account has been deleted.")
    else:
        st.warning(
            "This will permanently delete your WatchDog account and cannot be undone. "
            "Only continue if you're sure."
        )
        if st.button("Yes, Delete My Account", type="primary"):
            try:
                confirm_self_delete(token)
                st.session_state[done_key] = True
                st.rerun()
            except ApiError as e:
                st.error(f"Could not delete account: {e.detail}")
            except Exception:
                st.error("Could not reach the WatchDog server. Please try again shortly.")