import json
import streamlit as st

_PALETTES = {
    "watchdog": {"background": "#0A1A2F", "text": "#C0C7D1", "accent": "#00E5FF", "header": "#0A1A2F"},
    "sensordog": {"background": "#1B140F", "text": "#E8DFD2", "accent": "#FF9800", "header": "#1B140F"},
}


def _load_palette(theme: str) -> dict:
    path = f"themes/{'wolf' if theme == 'watchdog' else 'sensor_dog'}/palette.json"
    try:
        with open(path) as f:
            data = json.load(f)
            if data:
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return _PALETTES[theme]


def current_palette() -> dict:
    theme = st.session_state.get("theme", "watchdog")
    return _load_palette(theme)


def inject_css():
    """Applies the active theme's accent/background across cards, buttons, and headers.
    Safe to call on every screen — cheap and idempotent."""
    p = current_palette()
    st.markdown(
        f"""
        <style>
        .card {{
            background: {p['background']};
            border: 1px solid {p['accent']}33;
            border-radius: 12px;
            padding: 1.1rem 1.3rem;
            color: {p['text']};
            box-shadow: 0 2px 10px rgba(0,0,0,0.25);
        }}
        .card h3 {{
            color: {p['accent']};
            margin: 0.2rem 0 0 0;
            font-size: 1.8rem;
        }}
        .wd-badge {{
            display: inline-block;
            padding: 0.15rem 0.6rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.02em;
        }}
        .wd-badge-ok {{ background: #1e7e34; color: #eafff0; }}
        .wd-badge-warn {{ background: #b8860b; color: #fff8e6; }}
        .wd-badge-danger {{ background: #a12020; color: #ffecec; }}
        .wd-badge-muted {{ background: #444c56; color: #dfe3e8; }}

        [data-testid="stSidebar"] {{
            border-right: 1px solid {p['accent']}22;
        }}
        div.stButton > button[kind="primary"] {{
            background-color: {p['accent']};
            border-color: {p['accent']};
        }}
        hr {{ border-color: {p['accent']}55; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(text: str, kind: str = "muted") -> str:
    return f'<span class="wd-badge wd-badge-{kind}">{text}</span>'
