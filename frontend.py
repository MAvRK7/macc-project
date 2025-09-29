import streamlit as st
import requests
import time
import uuid
import re

BASE_URL = "https://macc-project.onrender.com"

st.set_page_config(page_title="🤖 MACC – Multi-Agent Code Collaborator", layout="wide")

# ---------------- Utility Functions ----------------
def slugify(text: str) -> str:
    """Turn spec text into a GitHub-friendly repo name."""
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text[:40]  # keep it short enough for repo names

def poll_updates(session_id: str):
    """Poll backend for project updates."""
    status_box = st.empty()
    code_area = st.text_area("Code Output", value=st.session_state.code, height=360, key="code_output_area")
    log_box = st.empty()

    try:
        with requests.post(
            f"{BASE_URL}/generate-project-stream",
            json={"spec": st.session_state.spec, "github_repo": st.session_state.github_repo},
            stream=True,
            timeout=90
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                msg = line.decode("utf-8")
                if '"type": "status"' in msg:
                    status = msg.split('"message": "')[1].split('"')[0]
                    with status_box:
                        st.write(f"📢 {status}")
                elif '"type": "code"' in msg:
                    code_line = msg.split('"message": "')[1].split('"')[0]
                    st.session_state.code += code_line + "\n"
                    code_area = st.text_area("Code Output", value=st.session_state.code, height=360, key="code_output_area")
                else:
                    with log_box:
                        st.write(msg)
    except Exception as e:
        st.error(f"❌ Error while streaming: {e}")

# ---------------- Session State ----------------
if "code" not in st.session_state:
    st.session_state.code = ""
if "spec" not in st.session_state:
    st.session_state.spec = "Build a Python CLI for weather forecasting with email alerts"
if "github_repo" not in st.session_state:
    st.session_state.github_repo = ""

# ---------------- UI Layout ----------------
st.title("🤖 MACC – Multi-Agent Code Collaborator")
st.markdown("Generate, review, and refine Python projects with AI agents.")

with st.form("project_form"):
    spec = st.text_area("Enter your project specification", value=st.session_state.spec, height=120)
    github_repo = st.text_input("GitHub repo (optional, leave blank to auto-create)", value=st.session_state.github_repo)
    submitted = st.form_submit_button("🚀 Generate Project")

if submitted:
    st.session_state.spec = spec
    if not github_repo.strip():
        st.session_state.github_repo = f"{slugify(spec)}-{uuid.uuid4().hex[:6]}"
    else:
        st.session_state.github_repo = github_repo
    st.session_state.code = ""  # reset code
    sid = str(uuid.uuid4())
    st.session_state.session_id = sid
    st.write(f"**Session id:** {sid}")
    poll_updates(sid)

# ---------------- Suggestion Box ----------------
if "session_id" in st.session_state:
    suggestion = st.text_input("💡 Suggest a refinement")
    if st.button("Apply Suggestion"):
        try:
            with requests.post(
                f"{BASE_URL}/suggest-changes-stream",
                json={"session_id": st.session_state.session_id, "suggestion": suggestion},
                stream=True,
                timeout=90
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    msg = line.decode("utf-8")
                    if '"type": "status"' in msg:
                        st.write(f"📢 {msg}")
                    elif '"type": "code"' in msg:
                        code_line = msg.split('"message": "')[1].split('"')[0]
                        st.session_state.code += code_line + "\n"
                        st.text_area("Code Output", value=st.session_state.code, height=360, key="code_output_area")
        except Exception as e:
            st.error(f"❌ Error during refinement: {e}")
