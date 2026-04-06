# The Multi-Agent AI Code Collaborator (MACC)

<img width="1024" height="572" alt="image" src="https://github.com/user-attachments/assets/40593ac0-4ee6-4f37-a985-4c06d1a5aeb1" />


## Overview

The Multi-Agent AI Code Collaborator (MACC) is a web application that leverages AI agents to generate, review, and refine Python code based on user-provided project specifications. Built with LangGraph and powered by Mistral's mistral-small-latest as the primary and OpenRouter’s qwen/qwen3-coder:free model as fallback, MACC uses a multi-agent workflow (Planner, Coder, Reviewer) to break down specifications into tasks, generate code, and incorporate user suggestions. The generated code is pushed to a specified GitHub repository.

## Features

- Project Generation: Enter a project specification and GitHub repository to generate tasks and Python code.
- Iterative Suggestions: Submit suggestions to refine generated code, with updates pushed to GitHub.
- Dynamic Suggestions: The model automatically gives suggestions to improve the generated code.
- Web Interface: Streamlit-based frontend for user input and output display.
- Can show the model's thinking process. Enhanced transparency.
- FastAPI Backend: Handles AI agent workflows and GitHub integration.
- Free Deployment: Runs on Render (backend) and Streamlit Community Cloud (frontend) free tiers.

## Deployment

MACC is deployed as two components:

- Backend: A FastAPI server (main.py) on Render at https://macc-project-n5v3.onrender.com .
- Frontend: A Streamlit app (frontend.py) on Streamlit Community Cloud at https://macc-project-mhyoeztobvzxbgslmpeu7v.streamlit.app .
- GitHub Repository: A new repository according to the name of the project.

## Requirements
* Python: 3.12

Dependencies: Listed in requirements.txt:

Web frameworks:

- fastapi==0.115.0
- uvicorn==0.30.6
- streamlit==1.39.0

Environmenral Variables:

- python-dotenv==1.0.1

LangGraph
- langgraph>=0.2.0

LLM clients

- openai==1.58.0
- mistralai==1.5.0

GitHub API

- PyGithub==2.4.0

HTTP requests (backend + frontend)

- requests==2.32.3

Pydantic for models / validation

- pydantic==2.9.0

CLI helpers

- click==8.1.7

Others

- setuptools<82.0.0
- wheel

Environment Variables:

- OPENROUTER_API_KEY: Obtain from OpenRouter.

- GITHUB_TOKEN: A GitHub personal access token with repo scope.
  
- MISTRAL_API_KEY: Obtain from https://mistral.ai

## Setup Instructions

Local Setup

1. Clone the Repository:

```
git clone https://github.com/MAvRK7/macc-project.git
cd macc-project
```

2. Create Virtual Environment:
```
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install Dependencies:

```
pip install -r requirements.txt
```

4. Set Environment Variables:

- Create a .env file in the project root:

```
OPENROUTER_API_KEY=your_openrouter_api_key
GITHUB_TOKEN=your_github_token
MISTRAL_API_KEY=your_mistral_api_key
```

5. Run the Backend:

```
python main.py
```

6. streamlit run frontend.py

```
python -m streamlit run "frontend.py"
```

- Access the Streamlit app at http://localhost:8501.

## Deploy to Render (Backend)

1. Log in to Render: Go to dashboard.render.com.
2. Create Web Service:
- Select MAvRK7/macc-project repository or the repository where you cloned this project 
- Environment: Docker
- Dockerfile Path: Dockerfile
- Instance Type: Free
- Environment Variables:
  - OPENROUTER_API_KEY: Your OpenRouter API key.
  - GITHUB_TOKEN: Your GitHub token.
  - MISTRAL_API_KEY: Your Mistral API key
3.Deploy: Click “Manual Deploy” > “Deploy latest commit.”
4. Verify: Check https://macc-project-n5v3.onrender.com (returns {"message": "MACC API running - all good"}) and /docs.

## Deploy to Streamlit Community Cloud (Frontend)

1. Log in to Streamlit: Go to share.streamlit.io.
2. Create App:
- Repository: MAvRK7/macc-project
- Branch: main
- Main file path: frontend.py
- Python version: 3.12
3. Set Secrets:
- In “Edit Secrets,” add:
  ```
  [api]
  BASE_URL = "https://macc-project-n5v3.onrender.com"
  ```
4. Deploy: Click “Deploy” or “Reboot.”
5. Verify: Access at https://macc-project.streamlit.app.

## Usage

1. Open the Streamlit App: Visit https://macc-project.streamlit.app.
2. Generate a Project:
3. Enter a project specification (e.g., “Build a Python CLI for weather forecasting with email alerts”).
4. Enter your GitHub repository (e.g., MAvRK7/macc-project) OR leave it blank for getting an auto generated repo name
5. Click “Generate Project” to view tasks, generated code, and a GitHub link.
6. Submit Suggestions:
7. Enter a suggestion (e.g., “Add error handling for API calls”).
8. Click “Submit Suggestion” to refine the code and update the GitHub repository.
9. Check GitHub: Verify the generated main.py in MAvRK7/macc-project.   

## Troubleshooting

- Render “Not Found” Error:
  - Ensure you access /docs or /generate-project (e.g., https://macc-project-1.onrender.com/docs).
  - Check Render logs: Dashboard > macc-api > Logs.

- Streamlit “Error contacting backend service”:
  - Verify BASE_URL in Streamlit secrets.
  - Ping https://macc-project-n5v3.onrender.com to prevent Render free tier hibernation.

- Check Streamlit logs: share.streamlit.io > Manage app > Logs.

## Known Limitations

- Render Free Tier: Services spin down after 15 minutes of inactivity, causing 30-60 second delays on first request. Use an uptime monitor (e.g., UptimeRobot) to keep it active.
- Input Validation: Specifications and suggestions must be at least 3 characters; GitHub repo must be in username/repo format.
- GitHub Integration: Requires a valid GITHUB_TOKEN with repo scope.

## Contributing

- Fork the repository.
- Create a feature branch: git checkout -b feature/your-feature.
- Commit changes: git commit -m "Add your feature".
- Push to the branch: git push origin feature/your-feature.
- Open a pull request.

## License

This project is licensed under the MIT License.

## Acknowledgments

- Powered by LangGrpah, Mistral and OpenRouter.
- Deployed using Render and Streamlit Community Cloud.


## Screenshot of the frontend streamlit app

Entering project sepcification

<img width="1440" height="778" alt="Screenshot 2025-10-01 at 1 30 36 PM" src="https://github.com/user-attachments/assets/219a6850-daf1-4e12-b989-e0e2dcbd2fef" />

Adding suggestions

<img width="1440" height="778" alt="image" src="https://github.com/user-attachments/assets/34f70923-8c78-4dfc-8097-e21d7e2db5f7" />

    

   
