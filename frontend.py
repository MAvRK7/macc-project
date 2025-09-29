import streamlit as st
import requests
import json
import time
import uuid

st.set_page_config(page_title="MACC - Multi-Agent AI Code Collaborator", layout="wide")

st.title("MACC - Multi-Agent AI Code Collaborator")
st.markdown(
    "Generate projects, review code, and refine them using multi-agent AI collaboration."
)

# ---------------- Config ----------------
BASE_URL = st.secrets["api"]["BASE_URL"]

# Initialize session state
if "session_id" not in st.session_state:
    st.session_state.session_id = None
    st.session_state.tasks = None
    st.session_state.code = ""
    st.session_state.repo_url = None
    st.session_state.description = ""
    st.session_state.status_msgs = []

# ---------------- Utilities ----------------
def stream_post(url, json_data):
    try:
        with requests.post(url, json=json_data, stream=True, timeout=300) as response:
            if response.status_code != 200:
                st.error(f"Error: {response.status_code} - {response.text}")
                return
            for line in response.iter_lines():
                if line:
                    try:
                        msg = json.loads(line.decode())
                        if msg["type"] == "status":
                            st.session_state.status_msgs.append(msg["message"])
                        elif msg["type"] == "code":
                            st.session_state.code += msg["message"] + "\n"
                        st.experimental_rerun()
                    except Exception as e:
                        st.warning(f"Malformed message: {line}")
    except requests.exceptions.RequestException as e:
        st.error(f"Error contacting backend: {e}")

# ---------------- Step 1: Generate Project ----------------
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
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.repo_url = None
        st.session_state.description = ""
        stream_post(f"{BASE_URL}/generate-project-stream", {"spec": spec, "github_repo": github_repo})

# ---------------- Step 2: Display Status ----------------
st.subheader("Project Status")
status_panel = st.empty()
with status_panel.container():
    for msg in st.session_state.status_msgs:
        st.markdown(f"- {msg}")

# ---------------- Step 3: Display Generated Code ----------------
st.subheader("Generated Code")
code_panel = st.empty()
with code_panel.container():
    st.text_area("Code Output", value=st.session_state.code, height=400, key="code_output")

# ---------------- Step 4: Project Description ----------------
if st.session_state.code.strip() and not st.session_state.description:
    st.session_state.description = (
        f"This project implements: {spec}\n\n"
        "You can review the code below and suggest improvements or commit to GitHub."
    )

if st.session_state.description:
    st.markdown(f"**Project Description:** {st.session_state.description}")

# ---------------- Step 5: Commit to GitHub ----------------
if st.session_state.code.strip():
    if st.button("Commit to GitHub"):
        if not st.session_state.session_id or not st.session_state.repo_url:
            st.warning("Session not fully initialized or repo URL not available yet.")
        else:
            st.success(f"Code committed to GitHub: {st.session_state.repo_url}")

# ---------------- Step 6: Suggest Changes ----------------
if st.session_state.code.strip():
    st.subheader("Step 2: Suggest changes")
    suggestion = st.text_area("Enter suggestion for refinement", "")
    if st.button("Submit Suggestion"):
        if not suggestion.strip():
            st.warning("Please provide a suggestion.")
        else:
            st.session_state.status_msgs.append("Submitting suggestion...")
            stream_post(
                f"{BASE_URL}/suggest-changes-stream",
                {"session_id": st.session_state.session_id, "suggestion": suggestion},
            )
