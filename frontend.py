import streamlit as st
import requests
import uuid

# ------------------ Config ------------------
BASE_URL = st.secrets["api"]["BASE_URL"]

st.set_page_config(page_title="MACC - Multi-Agent Code Collaborator", layout="wide")

st.title("🤖 MACC - Multi-Agent Code Collaborator")

# ------------------ Session State ------------------
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "code" not in st.session_state:
    st.session_state.code = ""
if "repo_url" not in st.session_state:
    st.session_state.repo_url = ""

# ------------------ Project Input ------------------
st.subheader("📝 Enter Project Specification")
spec = st.text_area(
    "Project description or prompt",
    value="Build a Python CLI for weather forecasting with email alerts",
    height=120
)

github_repo_input = st.text_input(
    "GitHub repo (optional, leave blank to auto-create)",
    value=""
)

# ------------------ Helper Functions ------------------
def generate_repo_name(spec_text):
    """Generate a friendly repo name from the project spec"""
    base = spec_text.lower().strip().replace(" ", "-")
    base = "".join(c for c in base if c.isalnum() or c == "-")
    return f"{base[:50]}-{uuid.uuid4().hex[:6]}"

def generate_project():
    """Call backend to generate project"""
    st.session_state.code = ""
    st.session_state.session_id = None
    st.session_state.repo_url = ""

    repo_name = github_repo_input.strip() or generate_repo_name(spec)

    payload = {
        "spec": spec,
        "github_repo": repo_name
    }

    try:
        resp = requests.post(f"{BASE_URL}/generate-project", json=payload, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            st.session_state.code = data.get("code", "")
            st.session_state.repo_url = data.get("repo_url", "")
            st.session_state.session_id = data.get("session_id", str(uuid.uuid4()))
            st.success("✅ Project generated successfully!")
        else:
            st.error(f"❌ Error generating project: {resp.status_code} {resp.reason}")
            st.text(resp.text)
    except Exception as e:
        st.error(f"❌ Request failed: {e}")

def apply_suggestion(suggestion_text):
    """Send user suggestion to backend and update code"""
    if not st.session_state.session_id:
        st.warning("Please generate a project first.")
        return

    if not suggestion_text.strip():
        st.warning("Enter a suggestion first.")
        return

    payload = {
        "session_id": st.session_state.session_id,
        "suggestion": suggestion_text.strip()
    }

    try:
        resp = requests.post(f"{BASE_URL}/suggest-changes", json=payload, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            st.session_state.code = data.get("code", st.session_state.code)
            st.session_state.repo_url = data.get("repo_url", st.session_state.repo_url)
            st.success("✅ Suggestion applied successfully!")
        else:
            st.error(f"❌ Error applying suggestion: {resp.status_code} {resp.reason}")
            st.text(resp.text)
    except Exception as e:
        st.error(f"❌ Request failed: {e}")

# ------------------ Generate Button ------------------
if st.button("🚀 Generate Project"):
    if not spec.strip():
        st.warning("Please enter a project specification.")
    else:
        generate_project()

# ------------------ Display Code ------------------
if st.session_state.code:
    st.subheader("💻 Generated Code")
    st.code(st.session_state.code, language="python")

# ------------------ GitHub Repo Link ------------------
if st.session_state.repo_url:
    st.subheader("📦 Repository URL")
    st.write(f"[{st.session_state.repo_url}]({st.session_state.repo_url})")

# ------------------ User Suggestions ------------------
if st.session_state.code:
    st.subheader("💡 Suggest Changes / Improvements")
    suggestion_input = st.text_area("Enter your suggestion for the generated code", height=80)

    if st.button("Apply Suggestion"):
        apply_suggestion(suggestion_input)
        if st.session_state.code:
            st.code(st.session_state.code, language="python")
