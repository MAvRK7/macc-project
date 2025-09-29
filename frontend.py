import streamlit as st
import requests
import json
import time

st.set_page_config(page_title="MACC - AI Code Collaborator", layout="wide")
st.title("MACC - Multi-Agent AI Code Collaborator")

BASE_URL = st.secrets["api"]["BASE_URL"]

# ---------------- Session state ----------------
if "session_id" not in st.session_state:
    st.session_state.update({
        "session_id": None,
        "status_msgs": [],
        "code": "",
        "repo_url": None
    })

# ---------------- Panels ----------------
status_panel = st.empty()
code_panel = st.empty()

def display_status():
    with status_panel.container():
        for m in st.session_state.status_msgs:
            if m.startswith("Error") or m.startswith("Backend"):
                st.error(m)
            else:
                st.info(m)

def display_code():
    with code_panel.container():
        st.text_area("Generated Code", value=st.session_state.code, height=400)
        if st.button("Copy Code"):
            st.experimental_set_query_params()
            st.success("Code copied! (Ctrl+C)")

# ---------------- Project generation ----------------
st.subheader("Step 1: Generate a project")
spec = st.text_area("Project specification", "Build a hello world app")
github_repo = st.text_input("GitHub repo (optional)","")

if st.button("Generate Project"):
    st.session_state.status_msgs = []
    st.session_state.code = ""
    st.session_state.session_id = None
    try:
        response = requests.post(f"{BASE_URL}/generate-project-stream",
                                 json={"spec": spec, "github_repo": github_repo},
                                 stream=True, timeout=300)
        session_id = str(time.time())
        st.session_state.session_id = session_id

        for line in response.iter_lines():
            if line:
                msg = json.loads(line.decode())
                if msg["type"] == "status":
                    st.session_state.status_msgs.append(msg["message"])
                    display_status()
                elif msg["type"] == "code":
                    st.session_state.code += msg["message"] + "\n"
                    display_code()
    except requests.exceptions.RequestException as e:
        st.error(f"Backend error: {str(e)}")

# ---------------- Commit ----------------
if st.session_state.code:
    st.subheader("Step 2: Commit to GitHub")
    if st.button("Commit code"):
        try:
            res = requests.post(f"{BASE_URL}/commit", json={"session_id": st.session_state.session_id})
            if res.status_code == 200:
                st.success(f"Code committed! URL: {res.json().get('repo_url')}")
            else:
                st.error(f"Error committing code: {res.text}")
        except requests.exceptions.RequestException as e:
            st.error(f"Backend error: {str(e)}")

# ---------------- Suggest changes ----------------
if st.session_state.code:
    st.subheader("Step 3: Suggest changes")
    suggestion = st.text_area("Enter suggestion","")
    if st.button("Submit suggestion") and suggestion.strip():
        try:
            response = requests.post(f"{BASE_URL}/suggest-changes-stream",
                                     json={"session_id": st.session_state.session_id, "suggestion": suggestion},
                                     stream=True, timeout=300)
            for line in response.iter_lines():
                if line:
                    msg = json.loads(line.decode())
                    if msg["type"] == "status":
                        st.session_state.status_msgs.append(msg["message"])
                        display_status()
                    elif msg["type"] == "code":
                        st.session_state.code += msg["message"] + "\n"
                        display_code()
        except requests.exceptions.RequestException as e:
            st.error(f"Backend error: {str(e)}")
