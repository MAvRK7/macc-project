import streamlit as st
import requests

st.title("MACC - Multi-Agent AI Code Collaborator")

# Use BASE_URL from Streamlit secrets
BASE_URL = st.secrets["api"]["BASE_URL"]

# Initialize session state
if "session_id" not in st.session_state:
    st.session_state.session_id = None
    st.session_state.tasks = None
    st.session_state.code = None
    st.session_state.repo_url = None

# Input for initial project specification
spec = st.text_area(
    "Enter your project specification",
    "Build a Python CLI for weather forecasting with email alerts"
)
github_repo = st.text_input(
    "GitHub repo (e.g., username/repo)",
    "MAvRK7/macc-project"
)

if st.button("Generate Project"):
    try:
        response = requests.post(
            f"{BASE_URL}/generate-project",
            json={"spec": spec, "github_repo": github_repo},
            timeout=60  # Increased timeout for Render spin-up
        )
        if response.status_code == 200:
            result = response.json()["result"]
            st.session_state.session_id = result.get("session_id")
            st.session_state.tasks = result.get("tasks")
            st.session_state.code = result.get("code")
            st.session_state.repo_url = result.get("repo_url")

            st.write("### Generated Tasks")
            st.json(st.session_state.tasks)

            st.write("### Generated Code")
            st.code(st.session_state.code, language="python")

            st.write(f"[View on GitHub]({st.session_state.repo_url})")
        else:
            st.error(f"Error: {response.status_code} - {response.json().get('detail', response.text)}")
    except requests.exceptions.RequestException as e:
        st.error(f"Error contacting backend service: {str(e)}")
        st.error(f"Backend URL: {BASE_URL}")

# Input for suggestions
if st.session_state.session_id:
    suggestion = st.text_area("Suggest changes to the generated code", "")
    if st.button("Submit Suggestion"):
        try:
            response = requests.post(
                f"{BASE_URL}/suggest-changes",
                json={"session_id": st.session_state.session_id, "suggestion": suggestion},
                timeout=60  # Increased timeout
            )
            if response.status_code == 200:
                result = response.json()["result"]
                st.session_state.tasks = result.get("tasks")
                st.session_state.code = result.get("code")
                st.session_state.repo_url = result.get("repo_url")

                st.write("### Updated Tasks")
                st.json(st.session_state.tasks)

                st.write("### Updated Code")
                st.code(st.session_state.code, language="python")

                st.write(f"[View on GitHub]({st.session_state.repo_url})")
            else:
                st.error(f"Error: {response.status_code} - {response.json().get('detail', response.text)}")
        except requests.exceptions.RequestException as e:
            st.error(f"Error contacting backend service: {str(e)}")
            st.error(f"Backend URL: {BASE_URL}")
