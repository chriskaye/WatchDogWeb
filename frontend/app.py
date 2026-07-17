import streamlit as st

# Hide sidebar
st.markdown("""
<style>
section[data-testid="stSidebar"] { display: none; }
.block-container { padding-top: 1rem !important; }
</style>
""", unsafe_allow_html=True)

st.set_page_config(
    page_title="WatchDog",
    page_icon="assets/favicon.ico"
)

# ---------- SESSION STATE ----------
if "mode" not in st.session_state:
    st.session_state.mode = None   # None, "login", "create"

# ---------- LANDING PAGE CONTENT ----------
with st.container(horizontal_alignment="center"):
    st.title("WatchDog", text_alignment="center")
    st.markdown("---")

    # Big banner before click, small banner after click
    if st.session_state.mode is None:
        st.image("assets/watchdog_banner.png",
                 caption="Intelligent Environmental Monitoring Systems")
    else:
        st.image("assets/watchdog_banner.png",
                 caption="Intelligent Environmental Monitoring Systems",
                 width=300)

    st.markdown("---")

# ---------- BUTTON ROW (only when no form is active) ----------
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
elif st.session_state.mode == "login":
    st.subheader("Log In")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    colA, colB = st.columns(2)
    with colA:
        if st.button("Submit Login", type="primary", width="stretch"):
            st.session_state.login_email = email
            st.session_state.login_password = password
            st.switch_page("pages/_Login.py")

    with colB:
        if st.button("Cancel", type="secondary", width="stretch"):
            st.session_state.mode = None
            st.rerun()

# ---------- CREATE ACCOUNT FORM ----------
elif st.session_state.mode == "create":
    st.subheader("Create Account")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    confirm = st.text_input("Confirm Password", type="password")

    colA, colB = st.columns(2)
    with colA:
        if st.button("Submit Account Creation", type="primary", width="stretch"):
            st.session_state.new_email = email
            st.session_state.new_password = password
            st.session_state.new_confirm = confirm
            st.switch_page("pages/_CreateAccount.py")

    with colB:
        if st.button("Cancel", type="secondary", width="stretch"):
            st.session_state.mode = None
            st.rerun()
