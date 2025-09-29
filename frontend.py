import streamlit as st
import requests
import json
import uuid
import streamlit.components.v1 as components

st.set_page_config(page_title="MACC - Multi-Agent AI Code Collaborator", layout="wide")
st.title("MACC - Multi-Agent AI Code Collaborator")

# ------------------- Configuration -------------------
BASE_URL = st.secrets["api"]["BASE_URL"]

# ------------------- Session State -------------------
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.tasks = []
    st.session_state.code = ""
    st.session_state.repo_url = None
    st.session_state.status_msgs = []

status_panel = st.empty()
code_panel = st.empty()

# ------------------- Helper Functions -------------------
def stream_backend(url, payload):
    try:
        with requests.post(url, json=payload, stream=True, timeout=None) as response:
            if response.status_code != 200:
                st.error(f"Error: {response.status_code} - {response.text}")
                return

            for line in response.iter_lines():
                if line:
                    msg = json.loads(line.decode())
                    if msg["type"] == "status":
                        st.session_state.status_msgs.append(msg["message"])
                        status_panel.text("\n".join(st.session_state.status_msgs))
                    elif msg["type"] == "code":
                        st.session_state.code += msg["message"] + "\n"
                        code_panel.text_area("Code Output", value=st.session_state.code, height=400)
    except requests.exceptions.RequestException as e:
        st.error(f"Error contacting backend: {str(e)}")

def copy_button(code):
    components.html(f"""
        <button onclick="navigator.clipboard.writeText(`{code}`)">Copy Code</button>
    """, height=50)

# ------------------- Project Generation -------------------
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
        st.session_state.repo_url = None

        st.spinner("Starting project generation...")
        payload = {
            "spec": spec,
            "github_repo": github_repo
        }
        stream_backend(f"{BASE_URL}/generate-project-stream", payload)
        st.success("Project generation completed!")

# ------------------- Display Code and Status -------------------
st.subheader("Project Status")
status_panel.text("\n".join(st.session_state.status_msgs))

st.subheader("Generated Code")
code_panel.text_area("Code Output", value=st.session_state.code, height=400)
copy_button(st.session_state.code)

# ------------------- Commit Option -------------------
if st.session_state.code.strip():
    if st.button("Commit to GitHub"):
        if not st.session_state.session_id:
            st.warning("Session ID not available.")
        else:
            # Trigger commit via backend by sending a no-op suggestion "commit"
            payload = {"session_id": st.session_state.session_id, "suggestion": "commit"}
            stream_backend(f"{BASE_URL}/suggest-changes-stream", payload)
            st.success(f"Code committed to GitHub: {st.session_state.repo_url}")

# ------------------- Suggest Changes -------------------
if st.session_state.code.strip():
    st.subheader("Step 2: Suggest changes")
    suggestion = st.text_area("Enter suggestion for refinement", "")
    if st.button("Submit Suggestion"):
        if not suggestion.strip():
            st.warning("Please provide a suggestion.")
        else:
            st.session_state.status_msgs.append("Submitting suggestion...")
            payload = {"session_id": st.session_state.session_id, "suggestion": suggestion}
            stream_backend(f"{BASE_URL}/suggest-changes-stream", payload)
            st.success("Suggestion applied!")
