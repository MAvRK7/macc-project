import streamlit as st
import requests
import time

BASE_URL = st.secrets["api"]["BASE_URL"]

# Session State
for key in ["keep_alive", "show_thinking", "session_id", "code", "description", 
            "thinking", "suggestions", "repo_url", "token_info"]:
    if key not in st.session_state:
        st.session_state[key] = False if key in ["keep_alive", "show_thinking"] else "" if key != "token_info" else {}

# Keep Render Alive
if st.session_state.keep_alive:
    if "last_ping" not in st.session_state or time.time() - st.session_state.last_ping > 600:
        try:
            requests.get(f"{BASE_URL}/", timeout=5)
            st.session_state.last_ping = time.time()
        except:
            pass

st.title("🛠 MACC - Multi-Agent AI Code Collaborator")
st.caption("LangGraph-powered • Multiple Refinements")

# Toggles
col1, col2 = st.columns([3, 2])
with col1:
    spec = st.text_area("Project Specification", height=100, 
                       placeholder="Build a Python CLI for weather forecasting...")
with col2:
    st.session_state.keep_alive = st.toggle("Keep Render Alive", value=st.session_state.keep_alive)
    st.session_state.show_thinking = st.toggle("Show Thinking", value=st.session_state.show_thinking)

github_repo = st.text_input("GitHub Repo (optional)", value="")

# ------------------ Helpers ------------------
def start_project(spec: str, github_repo: str = "") -> str | None:
    try:
        resp = requests.post(f"{BASE_URL}/generate-project", 
                           json={"spec": spec, "github_repo": github_repo}, timeout=20)
        resp.raise_for_status()
        return resp.json()["session_id"]
    except Exception as e:
        st.error(f"❌ Failed to start project: {e}")
        return None

def apply_suggestion(session_id: str, suggestion: str):
    if not suggestion or not suggestion.strip():
        st.warning("Please enter a suggestion")
        return None, None

    try:
        resp = requests.post(
            f"{BASE_URL}/suggest-changes", 
            json={"session_id": session_id, "suggestion": suggestion.strip()}, 
            timeout=20
        )
        resp.raise_for_status()
        st.success("✅ Suggestion applied! Updating code...")
        
        # Important: Refresh the full state
        return poll_updates(session_id)
    except Exception as e:
        st.error(f"❌ Failed to apply suggestion: {e}")
        return None, None


def poll_updates(session_id: str):
    """Improved polling - clears old code and updates everything"""
    status_container = st.empty()
    code_text = ""   # Reset code text

    done = False
    repo_url = None

    while not done:
        try:
            resp = requests.get(f"{BASE_URL}/updates/{session_id}", timeout=30)
            resp.raise_for_status()
            data = resp.json()

            done = data.get("done", False)
            repo_url = data.get("repo_url")

            for msg in data.get("messages", []):
                typ = msg.get("type")
                content = msg.get("message", "")

                if typ == "status":
                    status_container.write(f"📢 **{content}**")
                elif typ == "code":
                    code_text += content + "\n"
                elif typ == "description":
                    st.session_state.description = content
                elif typ == "thinking":
                    st.session_state.thinking = content
                elif typ == "suggestions":
                    st.session_state.suggestions = content
                elif typ == "token_info":
                    st.session_state.token_info = content

        except Exception as e:
            st.error(f"❌ Polling error: {e}")
            break

        time.sleep(0.6)

    # Update session state with latest code
    st.session_state.code = code_text
    st.session_state.repo_url = repo_url

    return code_text, repo_url


def commit_to_github(session_id: str):
    try:
        resp = requests.post(f"{BASE_URL}/commit", json={"session_id": session_id}, timeout=15)
        resp.raise_for_status()
        url = resp.json().get("repo_url")
        if url:
            st.success(f"✅ Committed! [Open Repo]({url})")
        return url
    except Exception as e:
        st.error(f"❌ Commit failed: {e}")
        return None

def show_cost_button():
    if st.button("💰 Show Estimated Cost"):
        ti = st.session_state.get("token_info", {})
        if ti.get("cost"):
            st.success(f"""
**Token Usage & Cost**
- Input: **{ti.get('input_tokens', 0):,}**
- Output: **{ti.get('output_tokens', 0):,}**
**Estimated Cost: ${ti.get('cost', 0):.5f}**
            """)
        else:
            st.info("No cost data available yet.")

#------------------DEBUG----------------------
def debug_token_info():
    if st.button("🔍 Debug Token Info"):
        st.write("Session State Debug:")
        st.write("token_info exists:", "token_info" in st.session_state)
        st.write("token_info content:", st.session_state.get("token_info", "NOT FOUND"))
        st.write("Full session keys:", list(st.session_state.keys()))

# Generate Button
if st.button("🚀 Generate Project", type="primary"):
    if spec.strip():
        with st.spinner("Running multi-agent workflow..."):
            session_id = start_project(spec, github_repo)
            if session_id:
                st.session_state.session_id = session_id
                poll_updates(session_id)

# Results Section
if st.session_state.get("code"):
    st.subheader("📝 English Description")
    st.info(st.session_state.get("description", "No description available."))

    if st.session_state.get("show_thinking") and st.session_state.get("thinking"):
        st.subheader("💡 Internal Thinking")
        st.markdown(st.session_state.thinking)

    st.subheader("✅ Generated Code")
    clean_code = st.session_state.code.replace("```python", "").replace("```", "").strip()
    st.code(clean_code, language="python")   # Removed height=500
            

    show_cost_button()
    debug_token_info()



    if st.session_state.get("suggestions"):
        st.subheader("💡 Smart Suggestions")
        st.markdown(st.session_state.suggestions)

    if st.session_state.get("repo_url"):
        st.markdown(f"[📂 Open on GitHub]({st.session_state.repo_url})")

# Refinement Section
st.subheader("🔄 Refine Code")
suggestion = st.text_area("Enter your suggestion:", 
                         placeholder="Change to BuzzFizz\nAdd input validation", height=90, key="suggestion_input")

col_a, col_b, col_c = st.columns([2, 2, 1])
with col_a:
    if st.button("Apply Suggestion"):
                if st.session_state.get("session_id") and suggestion.strip():
                    st.session_state.code, st.session_state.repo_url = apply_suggestion(
                        st.session_state.session_id, suggestion
                    )
                    st.rerun()   # Force refresh

with col_b:
    if st.button("I'm Happy - Start Fresh"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

with col_c:
    if st.button("Clear"):
        st.session_state.suggestion_input = ""

# Commit
if st.session_state.get("session_id") and st.session_state.get("code"):
    if st.button("💾 Commit to GitHub", type="primary"):
        commit_to_github(st.session_state.session_id)