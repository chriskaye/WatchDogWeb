import streamlit as st
from api_client import verify_email, ApiError

if "mode" not in st.session_state:
    st.session_state.mode = None  # None, "login", "create"

# ---------- EMAIL VERIFICATION LINK HANDLING ----------
verify_token = st.query_params.get("token")
if verify_token and not st.session_state.get("verification_handled"):
    st.session_state.verification_handled = True
    with st.container(horizontal_alignment="center"):
        st.title("WatchDog", text_alignment="center")
        st.markdown("---")
        try:
            verify_email(verify_token)
            st.success("Your email has been verified! You can now log in.")
        except ApiError as e:
            st.error(f"Verification failed: {e.detail}")
        except Exception:
            st.error("Could not reach the WatchDog server. Please try again shortly.")
        st.query_params.clear()
        if st.button("Continue to Log In"):
            st.session_state.mode = "login"
            st.rerun()
    st.stop()

# ---------- LANDING PAGE CONTENT ----------
with st.container(horizontal_alignment="center"):
    st.title("WatchDog", text_alignment="center")
    st.markdown("---")
    if st.session_state.mode is None:
        st.image("assets/watchdog_banner.png",
                 caption="Intelligent Environmental Monitoring Systems")
    else:
        st.image("assets/watchdog_banner.png",
                 caption="Intelligent Environmental Monitoring Systems",
                 width=300)
    st.markdown("---")

# ---------- BUTTON ROW ----------
if st.session_state.mode is None:
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Log In", type="primary", width="stretch"):
            st.session_state.mode = "login"
            st.rerun()
    with col2:
        if st.button("Create New Account", type="secondary", width="stretch"):
            st.session_state.mode = "create"
            st.rerun()

# ---------- LOGIN FORM ----------
# st.form (not bare widgets) is required here: Streamlit only flushes a text_input's
# in-progress value to session_state on blur, and tabbing between fields doesn't
# reliably fire that blur in the way clicking away does — the un-committed value silently
# never reaches Python. A form batches every widget inside it and force-flushes all of
# them together when the submit button fires, regardless of how focus left the last field.
# Use this pattern (st.form + st.form_submit_button) for every input screen in this app.
elif st.session_state.mode == "login":
    st.subheader("Log In")
    with st.form("login_form", border=False):
        email = st.text_input("Email", key="login_email_input")
        password = st.text_input("Password", type="password", key="login_password_input")

        colA, colB = st.columns(2)
        with colA:
            submitted = st.form_submit_button("Submit Login", type="primary", width="stretch")
        with colB:
            cancelled = st.form_submit_button("Cancel", type="secondary", width="stretch")

    if submitted:
        st.session_state.login_email = email
        st.session_state.login_password = password
        st.switch_page("screens/login.py")
    if cancelled:
        st.session_state.mode = None
        st.rerun()

# ---------- CREATE ACCOUNT FORM ----------
elif st.session_state.mode == "create":
    st.subheader("Create Account")
    with st.form("create_account_form", border=False):
        email = st.text_input("Email", key="create_email_input")
        password = st.text_input("Password", type="password", key="create_password_input")
        confirm = st.text_input("Confirm Password", type="password", key="create_confirm_input")

        colA, colB = st.columns(2)
        with colA:
            submitted = st.form_submit_button("Submit Account Creation", type="primary", width="stretch")
        with colB:
            cancelled = st.form_submit_button("Cancel", type="secondary", width="stretch")

    if submitted:
        st.session_state.new_email = email
        st.session_state.new_password = password
        st.session_state.new_confirm = confirm
        st.switch_page("screens/create_account.py")
    if cancelled:
        st.session_state.mode = None
        st.rerun()