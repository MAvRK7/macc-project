import streamlit as st
import requests
import json
import time

st.set_page_config(page_title="MACC - Multi-Agent AI Code Collaborator", layout="wide")

st.title("MACC - Multi-Agent AI Code Collaborator")

# API base URL from secrets
BASE_URL = st.secrets["api"]["BASE_URL"]

# Initialize session state
if "session_id" not in st.session_state:
    st.session_state.session_id = None
    st.session_state.tasks = None
    st.session_state.code = ""
    st.session_state.repo_url = None

if "status_msgs" not in st.session_state:
    st.session_state.status_msgs = []

# ---------------- Project Generation ----------------
st.subheader("Step 1: Generate a project")
spec = st.text_area(
    "Enter your project specification",
    "Build a Python CLI for weather forecasting with email alerts"
)
github_repo = st.text_input(
    "GitHub repo (optional, leave blank to auto-create)",
    ""
)

if st.button("Generate Project"):
    if not spec.strip():
        st.error("Please provide a project specification.")
    else:
        st.session_state.status_msgs = []
        st.session_state.code = ""
        st.session_state.session_id = None
        with st.spinner("Starting project generation..."):
            try:
                response = requests.post(
                    f"{BASE_URL}/generate-project-stream",
                    json={"spec": spec, "github_repo": github_repo},
                    stream=True,
                    timeout=300
                )
                if response.status_code != 200:
                    st.error(f"Error: {response.status_code} - {response.text}")
                else:
                    session_id = None
                    for line in response.iter_lines():
                        if line:
                            msg = json.loads(line.decode())
                            if msg["type"] == "status":
                                st.session_state.status_msgs.append(msg["message"])
                                st.experimental_rerun()
                            elif msg["type"] == "code":
                                st.session_state.code += msg["message"] + "\n"
                    # After completion
                    st.success("Project generation complete!")
            except requests.exceptions.RequestException as e:
                st.error(f"Error contacting backend: {str(e)}")

# ---------------- Display Status and Code ----------------
st.subheader("Project Status")
status_panel = st.empty()
with status_panel.container():
    for m in st.session_state.status_msgs:
        st.markdown(f"- {m}")

st.subheader("Generated Code")
code_panel = st.empty()
with code_panel.container():
    st.text_area("Code Output", value=st.session_state.code, height=400, key="code_output")
    if st.button("Copy Code"):
        st.experimental_set_query_params()  # Dummy to enable copy
        st.text("Code copied! (Use Ctrl+C)")

# ---------------- Commit Option ----------------
if st.session_state.code.strip():
    if st.button("Commit to GitHub"):
        if not st.session_state.session_id:
            st.warning("Session ID not available.")
        else:
            st.success(f"Code committed to GitHub: {st.session_state.repo_url}")

# ---------------- Suggest Changes ----------------
if st.session_state.code.strip():
    st.subheader("Step 2: Suggest changes")
    suggestion = st.text_area("Enter suggestion for refinement", "")
    if st.button("Submit Suggestion"):
        if not suggestion.strip():
            st.warning("Please provide a suggestion.")
        else:
            st.session_state.status_msgs.append("Submitting suggestion...")
            try:
                response = requests.post(
                    f"{BASE_URL}/suggest-changes-stream",
                    json={"session_id": st.session_state.session_id, "suggestion": suggestion},
                    stream=True,
                    timeout=300
                )
                if response.status_code != 200:
                    st.error(f"Error: {response.status_code} - {response.text}")
                else:
                    for line in response.iter_lines():
                        if line:
                            msg = json.loads(line.decode())
                            if msg["type"] == "status":
                                st.session_state.status_msgs.append(msg["message"])
                                st.experimental_rerun()
                            elif msg["type"] == "code":
                                st.session_state.code += msg["message"] + "\n"
                    st.success("Suggestion applied!")
            except requests.exceptions.RequestException as e:
                st.error(f"Error contacting backend: {str(e)}")
