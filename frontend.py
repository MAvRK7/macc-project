import streamlit as st
import requests
import json
import uuid
import time

# ----------------------- Config -----------------------
BASE_URL = st.secrets["api"]["BASE_URL"]  # e.g., "https://macc-project-n5v3.onrender.com"

# ----------------------- Helpers -----------------------
def stream_post(url, payload):
    """Stream updates from backend and update Streamlit UI"""
    session_id = str(uuid.uuid4())
    headers = {"Accept": "text/event-stream"}
    try:
        with requests.post(url, json=payload, headers=headers, stream=True, timeout=300) as response:
            if response.status_code != 200:
                st.error(f"❌ Error starting project: {response.status_code} {response.reason}")
                return None, None

            status_container = st.empty()
            code_container = st.empty()
            code_text = ""

            github_url = None

            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    msg_type = msg.get("type")
                    content = msg.get("message")
                    if msg_type == "status":
                        status_container.text(f"📢 {content}")
                        if "Code prepared on GitHub" in content:
                            github_url = content.split("Code prepared on GitHub:")[-1].strip()
                    elif msg_type == "code":
                        code_text += content + "\n"
                        code_container.text_area("Generated Code", value=code_text, height=400, key=str(uuid.uuid4()))
                except Exception as e:
                    st.warning(f"Error parsing message: {e}")
            return code_text, github_url
    except requests.exceptions.RequestException as e:
        st.error(f"❌ Error connecting to backend: {e}")
        return None, None

# ----------------------- UI -----------------------
st.title("🛠 MACC - Multi-Agent AI Code Collaborator")
st.write("Generate Python projects with AI agents. Enter your project specification below:")

default_prompt = "Build a Python CLI for weather forecasting with email alerts"
spec = st.text_area("Project Specification", value=default_prompt, height=80)
github_repo = st.text_input("GitHub Repo (optional)", value="")

if st.button("Generate Project"):
    st.session_state.generated_code = None
    st.session_state.github_url = None

    # Stream project generation
    code_text, github_url = stream_post(f"{BASE_URL}/generate-project-stream", {"spec": spec, "github_repo": github_repo})

    if code_text:
        st.session_state.generated_code = code_text
    if github_url:
        st.session_state.github_url = github_url

# ----------------------- Show Results -----------------------
if st.session_state.get("generated_code"):
    st.subheader("✅ Generated Code")
    st.code(st.session_state.generated_code, language="python")

if st.session_state.get("github_url"):
    st.subheader("📂 GitHub Repository")
    st.markdown(f"[Open on GitHub]({st.session_state.github_url})")

# ----------------------- Suggestions -----------------------
st.subheader("💡 Refine / Suggest Changes")
suggestion = st.text_area("Enter your suggestion to improve the code:")
if st.button("Apply Suggestion") and suggestion.strip():
    if not st.session_state.get("generated_code"):
        st.warning("Generate a project first before applying suggestions.")
    else:
        code_text, github_url = stream_post(f"{BASE_URL}/suggest-changes-stream", {"session_id": str(uuid.uuid4()), "suggestion": suggestion})
        if code_text:
            st.session_state.generated_code = code_text
        if github_url:
            st.session_state.github_url = github_url
