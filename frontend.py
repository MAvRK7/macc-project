import streamlit as st
import requests
import json

BASE_URL = "https://macc-project.onrender.com"  # replace with your API URL

st.set_page_config(page_title="MACC - Multi-Agent AI Code Collaborator", layout="wide")
st.title("🤖 MACC: Multi-Agent AI Code Collaborator")

if "code" not in st.session_state:
    st.session_state.code = ""
if "logs" not in st.session_state:
    st.session_state.logs = []

def stream_post(url, payload):
    try:
        with requests.post(url, json=payload, stream=True) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except:
                    continue

                if msg["type"] == "status":
                    st.session_state.logs.append(msg["message"])
                    log_box.text_area("Logs", value="\n".join(st.session_state.logs), height=200, key="logs_box")
                elif msg["type"] == "code":
                    st.session_state.code += msg["message"] + "\n"
                    code_box.text_area("Generated Code", value=st.session_state.code, height=400, key="code_box")
    except Exception as e:
        st.error(f"❌ Error while streaming: {str(e)}")

# --- UI Layout ---
spec = st.text_area("Enter your project specification", height=100)
github_repo = st.text_input("GitHub repo (optional, leave blank to auto-create)")

col1, col2 = st.columns(2)
with col1:
    if st.button("🚀 Generate Project"):
        st.session_state.code = ""
        st.session_state.logs = []
        stream_post(f"{BASE_URL}/generate-project-stream", {"spec": spec, "github_repo": github_repo})

with col2:
    suggestion = st.text_input("Refinement suggestion")
    if st.button("💡 Apply Suggestion"):
        if "session_id" not in st.session_state:
            st.error("⚠️ No active session found. Generate a project first.")
        else:
            stream_post(f"{BASE_URL}/suggest-changes-stream", {"session_id": st.session_state.session_id, "suggestion": suggestion})

# --- Placeholders for live updating ---
log_box = st.empty()
code_box = st.empty()
