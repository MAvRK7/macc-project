# frontend.py
import streamlit as st
import requests
import time
import json
import textwrap

st.set_page_config(page_title="MACC - Multi-Agent AI Code Collaborator", layout="wide")
st.title("🤖 MACC — Multi-Agent AI Code Collaborator")
st.markdown("Generate project code with multi-agent AI, review it, and commit to GitHub only when you're ready.")

# Replace with your Render URL or Streamlit secrets
BASE_URL = st.secrets["api"]["BASE_URL"] if "api" in st.secrets and "BASE_URL" in st.secrets["api"] else "https://macc-project.onrender.com"

# Session state
if "session_id" not in st.session_state:
    st.session_state.session_id = None
    st.session_state.statuses = []
    st.session_state.code = ""
    st.session_state.repo_url = None
    st.session_state.done = False

# Layout
col_l, col_r = st.columns([2, 1])

with col_l:
    st.subheader("Step 1 — Project specification")
    spec = st.text_area("Project specification", value="Build a Python CLI for weather forecasting with email alerts", height=120, key="spec_area")
    github_repo = st.text_input("GitHub repo (optional, leave blank to auto-create)", value="", key="repo_input")

    generate_btn = st.button("🚀 Generate Project")

with col_r:
    st.subheader("Session")
    st.write(f"Session id: {st.session_state.session_id or '(no active session)'}")
    st.write("Status log:")
    status_box = st.empty()
    st.write("Repository URL (after commit):")
    repo_box = st.empty()

# Code display (always present)
st.subheader("Generated Code")
code_box = st.empty()
# initialize code area once
code_box.text_area("Code Output", value=st.session_state.code, height=360, key="code_output")

# Controls
col_commit, col_suggest = st.columns([1, 2])
with col_commit:
    commit_btn = st.button("✅ Commit to GitHub")
with col_suggest:
    suggestion = st.text_input("Suggestion for refinement", key="suggest_input")
    suggest_btn = st.button("Apply Suggestion")

# Helper functions
def start_generation(spec_text: str, repo_name: str) -> str:
    """POST /generate-project and return session_id or raise."""
    try:
        r = requests.post(f"{BASE_URL}/generate-project", json={"spec": spec_text, "github_repo": repo_name}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data["session_id"]
    except Exception as e:
        st.error(f"Failed to start generation: {e}")
        return ""

def poll_updates(session_id: str, poll_interval: float = 1.0):
    """Poll /updates/{session_id} until done. Updates st.session_state in place."""
    if not session_id:
        st.error("No session id to poll.")
        return

    st.session_state.done = False
    while True:
        try:
            r = requests.get(f"{BASE_URL}/updates/{session_id}", timeout=30)
            r.raise_for_status()
            payload = r.json()
            messages = payload.get("messages", [])
            done = payload.get("done", False)
            repo_url = payload.get("repo_url")
            # process messages
            for m in messages:
                t = m.get("type")
                msg = m.get("message")
                if t == "status":
                    st.session_state.statuses.append(msg)
                elif t == "code":
                    # append code line
                    st.session_state.code += msg + "\n"
            if repo_url:
                st.session_state.repo_url = repo_url
            # update UI
            status_box.markdown("\n".join(f"- {s}" for s in st.session_state.statuses))
            code_box.text_area("Code Output", value=st.session_state.code, height=360, key="code_output")
            if st.session_state.repo_url:
                repo_box.write(st.session_state.repo_url)
            if done:
                st.session_state.done = True
                break
        except requests.exceptions.RequestException as e:
            st.error(f"Error polling updates: {e}")
            break
        time.sleep(poll_interval)

def start_refine(session_id: str, suggestion_text: str):
    try:
        r = requests.post(f"{BASE_URL}/suggest-changes", json={"session_id": session_id, "suggestion": suggestion_text}, timeout=10)
        r.raise_for_status()
        # returns session_id; then poll
        poll_updates(session_id)
    except Exception as e:
        st.error(f"Failed to start refinement: {e}")

def do_commit(session_id: str):
    try:
        r = requests.post(f"{BASE_URL}/commit", json={"session_id": session_id}, timeout=20)
        r.raise_for_status()
        data = r.json()
        url = data.get("repo_url")
        st.success(f"Committed to GitHub: {url}")
        st.session_state.repo_url = url
        repo_box.write(url)
    except Exception as e:
        st.error(f"Commit failed: {e}")

# Actions
if generate_btn:
    # reset
    st.session_state.statuses = []
    st.session_state.code = ""
    st.session_state.repo_url = None
    st.session_state.done = False
    st.session_state.session_id = ""
    # start
    sid = start_generation(spec, github_repo)
    if sid:
        st.session_state.session_id = sid
        # poll updates (blocking but updates placeholders)
        poll_updates(sid)
    else:
        st.error("Could not start generation. Check backend logs.")

if suggest_btn:
    if not st.session_state.session_id:
        st.warning("No active session — generate a project first.")
    elif not suggestion.strip():
        st.warning("Enter a suggestion to apply.")
    else:
        # apply suggestion in background via endpoint and poll
        start_refine(st.session_state.session_id, suggestion)

if commit_btn:
    if not st.session_state.session_id:
        st.warning("No active session — generate a project first.")
    else:
        do_commit(st.session_state.session_id)
