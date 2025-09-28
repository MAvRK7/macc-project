import streamlit as st
import requests

st.title("MACC - Multi-Agent AI Code Collaborator")
spec = st.text_area("Enter your project specification", "Build a Python CLI for weather forecasting with email alerts")
github_repo = st.text_input("GitHub repo (e.g., username/repo)", "MAvRK7/macc-project")
if st.button("Generate Project"):
    response = requests.post("http://localhost:8000/generate-project", json={"spec": spec, "github_repo": github_repo})
    if response.status_code == 200:
        result = response.json()["result"]
        st.write("### Generated Tasks")
        st.json(result["tasks"])
        st.write("### Generated Code")
        st.code(result["code"], language="python")
        st.write(f"[View on GitHub]({result['repo_url']})")
    else:
        st.error(f"Error: {response.json()['detail']}")