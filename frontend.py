import streamlit as st
import requests

st.title("MACC - Multi-Agent AI Code Collaborator")

# Initialize session state
if "session_id" not in st.session_state:
    st.session_state.session_id = None
    st.session_state.tasks = None
    st.session_state.code = None
    st.session_state.repo_url = None

# Input for initial project specification
spec = st.text_area("Enter your project specification", "Build a Python CLI for weather forecasting with email alerts")
github_repo = st.text_input("GitHub repo (e.g., username/repo)", "MAvRK7/macc-project")

if st.button("Generate Project"):
    response = requests.post("http://localhost:8000/generate-project", json={"spec": spec, "github_repo": github_repo})
    if response.status_code == 200:
        result = response.json()["result"]
        st.session_state.session_id = result["session_id"]
        st.session_state.tasks = result["tasks"]
        st.session_state.code = result["code"]
        st.session_state.repo_url = result["repo_url"]
        st.write("### Generated Tasks")
        st.json(st.session_state.tasks)
        st.write("### Generated Code")
        st.code(st.session_state.code, language="python")
        st.write(f"[View on GitHub]({st.session_state.repo_url})")
    else:
        st.error(f"Error: {response.json()['detail']}")

# Input for suggestions
if st.session_state.session_id:
    suggestion = st.text_area("Suggest changes to the generated code", "")
    if st.button("Submit Suggestion"):
        response = requests.post(
            "http://localhost:8000/suggest-changes",
            json={"session_id": st.session_state.session_id, "suggestion": suggestion}
        )
        if response.status_code == 200:
            result = response.json()["result"]
            st.session_state.tasks = result["tasks"]
            st.session_state.code = result["code"]
            st.session_state.repo_url = result["repo_url"]
            st.write("### Updated Tasks")
            st.json(st.session_state.tasks)
            st.write("### Updated Code")
            st.code(st.session_state.code, language="python")
            st.write(f"[View on GitHub]({st.session_state.repo_url})")
        else:
            st.error(f"Error: {response.json()['detail']}")
