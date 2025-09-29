import streamlit as st
import requests
import uuid

st.set_page_config(page_title="MACC - Multi-Agent AI Code Collaborator", layout="wide")
st.title("MACC - Multi-Agent AI Code Collaborator")

BASE_URL = st.secrets["api"]["BASE_URL"]

# Initialize session state
if "session_id" not in st.session_state:
    st.session_state.session_id = None
    st.session_state.tasks = None
    st.session_state.code = None
    st.session_state.repo_url = None
    st.session_state.status_logs = []

def add_status(msg):
    st.session_state.status_logs.append(msg)
    st.experimental_rerun()

# Inputs
spec = st.text_area(
    "Enter your project specification",
    "Build a Python CLI for weather forecasting with email alerts"
)
github_repo = st.text_input(
    "GitHub repo (optional, e.g., username/repo). Leave blank to auto-create",
    ""
)

# Generate Project
if st.button("Generate Project"):
    st.session_state.status_logs = []
    add_status("Starting project generation...")

    try:
        response = requests.post(
            f"{BASE_URL}/generate-project",
            json={"spec": spec, "github_repo": github_repo},
            timeout=300
        )
        if response.status_code == 200:
            result = response.json()["result"]
            st.session_state.session_id = result.get("session_id")
            st.session_state.tasks = result.get("tasks")
            st.session_state.code = result.get("code")
            st.session_state.repo_url = result.get("repo_url")
            add_status("Project generation completed!")
        else:
            add_status(f"Error: {response.status_code} - {response.json().get('detail', response.text)}")
    except requests.exceptions.RequestException as e:
        add_status(f"Error contacting backend: {str(e)}")

# Status logs
if st.session_state.status_logs:
    st.write("### Backend Status Updates")
    for msg in st.session_state.status_logs:
        st.write(f"- {msg}")

# Tasks display
if st.session_state.tasks:
    st.write("### Generated Tasks")
    st.json(st.session_state.tasks)

# Code display with scroll and copy
if st.session_state.code:
    st.write("### Generated Code")
    st.code(st.session_state.code, language="python", height=400)
    if st.button("Copy code to clipboard"):
        st.experimental_set_query_params(code=st.session_state.code)
        st.success("Code copied! (Ctrl+C)")

# Commit to GitHub confirmation
if st.session_state.session_id and st.session_state.code:
    if st.button("Commit to GitHub"):
        add_status("Committing code to GitHub...")
        try:
            response = requests.post(
                f"{BASE_URL}/suggest-changes",
                json={"session_id": st.session_state.session_id, "suggestion": "Initial commit"},
                timeout=120
            )
            if response.status_code == 200:
                result = response.json()["result"]
                st.session_state.repo_url = result.get("repo_url")
                add_status(f"Code committed successfully! [View on GitHub]({st.session_state.repo_url})")
            else:
                add_status(f"GitHub commit error: {response.status_code} - {response.json().get('detail', response.text)}")
        except requests.exceptions.RequestException as e:
            add_status(f"Error contacting backend for GitHub commit: {str(e)}")

# GitHub link
if st.session_state.repo_url:
    st.write(f"[View Project on GitHub]({st.session_state.repo_url})")
