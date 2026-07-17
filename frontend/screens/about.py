import streamlit as st

st.set_page_config(page_title="About", page_icon="favicon.ico", layout="wide")

st.markdown("## About WatchDog")
st.write("""
WatchDog is a modern sensor monitoring platform designed to provide real-time
visibility, anomaly detection, and intelligent alerting across distributed sensor networks.

This page will later include:
- Product overview
- Architecture diagram
- Security model
- Contact information
""")

if st.button("Back to Landing"):
    st.switch_page("pages/1_Landing.py")
