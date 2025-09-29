import streamlit as st
import requests
import time
import re

# -------------------------------
# Load BASE_URL from secrets
# -------------------------------
try:
    BASE_URL = st.secrets["api"]["BASE_URL"]
except Exception:
    st.error("❌ BASE_URL not found in Streamlit secrets. Please configure [.streamlit/secrets.toml].")
    st.stop()

# -------------------------------
# Utility: generate repo name
# -------------------------------
def generate_repo_name(prompt: str) -> str:
    """Generate a clean repo name from the prompt text."""
    text = prompt.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text[:30]  # truncate for safety

# -------------------------------
# Polling function
# -------------------------------
def poll_updates(session_id: str):
    placeholder = st.empty()  # container for dynamic updates

    while True:
        try:
            resp = requests.get(f"{BASE_URL}/status/{session_id}", timeout=10)
            resp.raise_for_status()
            data = resp.json()

            with placeholder.container():
                st.write("### Status log:")
                for i, msg in enumerate(data.get("status", [])):
                    st.write(f"📢 {msg}")

                repo_url = data.get("repo_url")
                if repo_url:
                    st.success(f"Repository URL: {repo_url}")

                code = data.get("code", "")
                if code:
                    st.text_area(
                        "Code Output",
                        value=code,
                        height=360,
                        key=f"code_output_{session_id}",  # unique key per session
                    )

            if data.get("done"):
                break

        except Exception as e:
            st.error(f"❌ Error fetching updates: {e}")
            break

        time.sleep(2)

# -------------------------------
# Streamlit UI
# -------------------------------
st.set_page_config(page_title="AI Project Generator", layout="wide")
st.title("🤖 AI Project Generator")

# Session state init
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "code" not in st.session_state:
    st.session_state.code = ""

# Prompt input (default value, editable)
default_prompt = "Build a Python CLI for weather forecasting with email alerts"
prompt = st.text_area(
    "Enter your project idea:",
    value=default_prompt,
    height=100,
    key="user_prompt",
)

# Start button
if st.button("🚀 Generate Project"):
    if not prompt.strip():
        st.warning("⚠️ Please enter a project prompt first.")
    else:
        repo_name = generate_repo_name(prompt)
        st.write(f"Auto-generated repo name: **{repo_name}**")

        try:
            resp = requests.post(
                f"{BASE_URL}/generate-project",
                json={"prompt": prompt, "repo_name": repo_name},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            sid = data.get("session_id")

            if not sid:
                st.error("❌ No session ID received from backend.")
            else:
                st.session_state.session_id = sid
                st.write(f"### Session\nSession id: `{sid}`")
                st.info("Starting project generation...")
                poll_updates(sid)

        except Exception as e:
            st.error(f"❌ Error starting project: {e}")

# If session already exists, resume polling
if st.session_state.session_id:
    st.write(f"### Current Session\nSession id: `{st.session_state.session_id}`")
