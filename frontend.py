import streamlit as st
import requests
import json

st.set_page_config(page_title="MACC - Multi-Agent AI Code Collaborator", layout="wide")
st.title("MACC - Multi-Agent AI Code Collaborator")

BASE_URL = st.secrets["api"]["BASE_URL"]

# Initialize session state
if "session_id" not in st.session_state:
    st.session_state.session_id = None
    st.session_state.code = ""
    st.session_state.status_msgs = []
    st.session_state.repo_url = None
    st.session_state.description = ""

# ---------------- Project Generation ----------------
st.subheader("Step 1: Generate a project")
spec = st.text_area("Enter your project specification", "")
github_repo = st.text_input("GitHub repo (optional, leave blank to auto-create)", "")

status_container = st.empty()
code_container = st.empty()
desc_container = st.empty()

def stream_post(url, payload):
    """Helper function to stream responses from backend safely."""
    try:
        with requests.post(url, json=payload, stream=True, timeout=300) as response:
            if response.status_code != 200:
                st.error(f"Error: {response.status_code} - {response.text}")
                return
            for line in response.iter_lines():
                if line:
                    try:
                        msg = json.loads(line.decode())
                        if msg.get("type") == "status":
                            st.session_state.status_msgs.append(msg["message"])
                        elif msg.get("type") == "code":
                            st.session_state.code += msg["message"] + "\n"
                        elif msg.get("type") == "description":
                            st.session_state.description = msg["message"]
                    except json.JSONDecodeError:
                        st.warning(f"Received malformed message: {line.decode()}")

                    # Update UI containers
                    status_container.markdown("\n".join(f"- {m}" for m in st.session_state.status_msgs))
                    code_container.text_area("Code Output", value=st.session_state.code, height=400)
                    desc_container.markdown(f"**Project Description:** {st.session_state.description}")
    except requests.exceptions.RequestException as e:
        st.error(f"Error contacting backend: {e}")

if st.button("Generate Project"):
    if not spec.strip():
        st.error("Please provide a project specification.")
    else:
        # Reset session state
        st.session_state.code = ""
        st.session_state.status_msgs = []
        st.session_state.description = ""
        st.session_state.session_id = None
        stream_post(f"{BASE_URL}/generate-project-stream", {"spec": spec, "github_repo": github_repo})

# ---------------- Commit to GitHub ----------------
if st.session_state.code.strip():
    st.subheader("Step 2: Commit Project")
    if st.button("Commit to GitHub"):
        try:
            payload = {"session_id": st.session_state.session_id, "code": st.session_state.code, "description": st.session_state.description}
            response = requests.post(f"{BASE_URL}/commit-project", json=payload)
            if response.status_code == 200:
                st.success(f"Code committed to GitHub: {st.session_state.repo_url}")
            else:
                st.error(f"GitHub commit failed: {response.status_code} - {response.text}")
        except requests.exceptions.RequestException as e:
            st.error(f"Error committing to GitHub: {e}")

# ---------------- Suggest Changes ----------------
if st.session_state.code.strip():
    st.subheader("Step 3: Suggest changes")
    suggestion = st.text_area("Enter suggestion for refinement", "")
    if st.button("Submit Suggestion"):
        if not suggestion.strip():
            st.warning("Please provide a suggestion.")
        else:
            st.session_state.status_msgs.append("Submitting suggestion...")
            stream_post(f"{BASE_URL}/suggest-changes-stream", {"session_id": st.session_state.session_id, "suggestion": suggestion})
