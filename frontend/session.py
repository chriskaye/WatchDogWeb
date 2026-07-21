import streamlit as st


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


def do_logout():
    """Clears the admin's own auth state, and any support session riding alongside it.

    The actual POST /support-access/sessions/{id}/end call gets wired in once
    api_client.py grows that endpoint (Phase 2) — for now this only clears local state,
    which is enough to stop the frontend from acting under a stale support_token.
    """
    st.session_state.logged_in = False
    st.session_state.access_token = None
    st.session_state.user = None
    st.session_state.roles = None
    st.session_state.support_session = None
    st.session_state.mode = None


def end_support_view():
    """Ends only the active support session — returns a WatchDog admin to their own
    view without logging them out of their own account. Same caveat as do_logout():
    the API call to formally end the session lands in Phase 2/15; this clears local
    state so the frontend stops using the support_token immediately either way."""
    st.session_state.support_session = None