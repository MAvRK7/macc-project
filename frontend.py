import streamlit as st
import requests

# Load backend URL from Streamlit secrets
BASE_URL = st.secrets["api"]["BASE_URL"]

st.title("MACC: Multi-Agent Code Creator")

st.markdown("Enter your project specification below and let MACC build the repo!")

spec = st.text_area("Project Specification", height=200)
github_repo = st.text_input("Optional GitHub Repo URL")

if st.button("Generate Project"):
    if not spec.strip():
        st.error("Please enter a project specification.")
    else:
        with st.spinner("Contacting backend... please wait (can take a while on first run)"):
            try:
                response = requests.post(
                    f"{BASE_URL}/generate-project",
                    json={"spec": spec, "github_repo": github_repo},
                    timeout=120,  # Increased timeout
                )

                if response.status_code == 200:
                    try:
                        data = response.json()
                        result = data.get("result", "")
                        st.success("Project generated successfully!")
                        st.code(result, language="markdown")
                    except ValueError:
                        # JSON parsing failed → show raw backend response
                        st.error("Backend returned invalid JSON. Here is the raw response:")
                        st.text(response.text)
                else:
                    st.error(f"Backend error {response.status_code}:")
                    st.text(response.text)

            except requests.exceptions.RequestException as e:
                st.error(f"Error contacting backend service: {e}")

st.markdown("---")
st.caption(f"Backend URL: {BASE_URL}")
