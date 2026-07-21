import streamlit as st
from api_client import end_support_session, ApiError


def init_session_state():
    """Ensures every session-state key the app depends on exists with a safe default.
    Call once at the top of app.py, before navigation is built.

    support_session is kept separate from access_token/user on purpose: a WatchDog
    admin can have their own login active *and* a read-only support view open at the
    same time, and each needs to be readable/clearable independently.
    """
    defaults = {
        "logged_in": False,
        "access_token": None,
        "user": None,
        "roles": None,           # {"global_role", "site_roles", "is_watchdog_admin"} — set at login
        "support_session": None,  # {"support_token", "session_id", "target_email", "expires_at"} or None
        "mode": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_active_token() -> str | None:
    """The token every screen/api_client call should use: the support_token when a
    support session is active, otherwise the admin/user's own access_token. Centralizing
    this means screens never have to know which one is "current" themselves."""
    support_session = st.session_state.get("support_session")
    if support_session:
        return support_session["support_token"]
    return st.session_state.get("access_token")


def do_logout():
    """Clears the admin's own auth state, and ends any support session riding alongside
    it (best-effort — a failed cleanup call shouldn't block the user from logging out)."""
    support_session = st.session_state.get("support_session")
    if support_session:
        try:
            end_support_session(st.session_state.access_token, support_session["session_id"])
        except ApiError:
            pass

    st.session_state.logged_in = False
    st.session_state.access_token = None
    st.session_state.user = None
    st.session_state.roles = None
    st.session_state.support_session = None
    st.session_state.mode = None


def end_support_view():
    """Ends only the active support session — returns a WatchDog admin to their own
    view without logging them out of their own account."""
    support_session = st.session_state.get("support_session")
    if not support_session:
        return
    try:
        end_support_session(st.session_state.access_token, support_session["session_id"])
    except ApiError:
        pass
    st.session_state.support_session = None