import os
import warnings
import asyncio
import logging
import requests
import subprocess
import uuid
import re
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from github import Github
from crewai_tools import BaseTool

# Logging Setup
logging.basicConfig(filename="agent_logs.txt", level=logging.INFO)
logging.info("Starting MACC application")

# Warnings Suppression & Event Loop Fix
os.environ["PYDANTIC_SKIP_VALIDATING_ASSIGNMENT"] = "1"
warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# Load environment variables
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY not found in .env")
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN not found in .env")

# FastAPI setup
app = FastAPI(title="MACC - Multi-Agent AI Code Collaborator")

# Root endpoint
@app.get("/")
async def root():
    return {"message": "MACC API running - all good"}

# Project context storage (in-memory for simplicity)
project_context = {}

class ProjectRequest(BaseModel):
    spec: str
    github_repo: str

class SuggestionRequest(BaseModel):
    session_id: str
    suggestion: str

# Tools
class GitHubTool(BaseTool):
    name: str = "GitHubTool"
    description: str = "Push code to a GitHub repository"

    def _run(self, repo_name: str, code: str, filename: str) -> str:
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        try:
            repo = user.get_repo(repo_name.split("/")[-1])
        except:
            repo = user.create_repo(repo_name.split("/")[-1], auto_init=True)
        repo.create_file(filename, "Initial commit", code)
        return f"Pushed to https://github.com/{repo_name}/blob/main/{filename}"

    def push_to_repo(self, repo_name: str, code: str, filename: str) -> str:
        return self._run(repo_name, code, filename)

class WebSearchTool(BaseTool):
    name: str = "WebSearchTool"
    description: str = "Search the web for best practices or references"

    def _run(self, query: str) -> str:
        response = requests.get(f"https://api.duckduckgo.com/?q={query}&format=json")
        return response.json().get("Abstract", "No results found")

class CodeExecTool(BaseTool):
    name: str = "CodeExecTool"
    description: str = "Execute Python code and return output"

    def _run(self, code: str) -> str:
        with open("temp.py", "w") as f:
            f.write(code)
        result = subprocess.run(["python", "temp.py"], capture_output=True, text=True)
        return result.stdout or result.stderr

# Instantiate tools
github_tool = GitHubTool()
web_search_tool = WebSearchTool()
code_exec_tool = CodeExecTool()

# Language Model (OpenRouter + Grok)
try:
    llm = ChatOpenAI(
        model="openrouter/x-ai/grok-4-fast:free",
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
        default_headers={
            "HTTP-Referer": "https://macc-project.streamlit.app",
            "X-Title": "MACC Project"
        }
    )
except Exception as e:
    raise ValueError(f"Failed to initialize LLM: {str(e)}")

# Agents
planner = Agent(
    role="Planner",
    goal="Break down project spec into tasks",
    backstory="Expert in project management and task decomposition.",
    llm=llm,
    tools=[web_search_tool]
)

coder = Agent(
    role="Coder",
    goal="Generate clean, functional code",
    backstory="Skilled programmer with expertise in Python and best practices.",
    llm=llm,
    tools=[code_exec_tool]
)

reviewer = Agent(
    role="Reviewer",
    goal="Ensure code quality and security, and incorporate user suggestions",
    backstory="Code quality specialist with deep knowledge of linting, security, and iterative refinement.",
    llm=llm,
    tools=[code_exec_tool]
)

# Input validation
def validate_inputs(spec: str, github_repo: str):
    if not spec or len(spec.strip()) < 3:
        raise ValueError("Project specification must be at least 3 characters long")
    if not github_repo or not re.match(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+$", github_repo):
        raise ValueError("GitHub repo must be in the format 'username/repo'")

# Main MACC Workflow
def run_macc_agents(spec, github_repo, session_id):
    logging.info(f"Running agents for spec: {spec}, repo: {github_repo}, session: {session_id}")

    validate_inputs(spec, github_repo)

    plan_task = Task(
        description=f"Break down this project spec into tasks: {spec}",
        agent=planner,
        expected_output="List of tasks in JSON format"
    )
    code_task = Task(
        description="Generate code for the given tasks",
        agent=coder,
        expected_output="Python code as a string"
    )
    review_task = Task(
        description="Review and improve the generated code",
        agent=reviewer,
        expected_output="Reviewed code and comments"
    )

    crew = Crew(agents=[planner, coder, reviewer], tasks=[plan_task, code_task, review_task])
    result = crew.kickoff()

    # Handle CrewOutput
    tasks = [task.dict() for task in result.tasks_output] if result.tasks_output else []
    generated_code = result.raw if hasattr(result, "raw") else ""

    if not generated_code:
        raise ValueError("No code was generated by the agents.")
    github_url = github_tool.push_to_repo(github_repo, generated_code, "main.py")

    # Store context
    project_context[session_id] = {
        "spec": spec,
        "github_repo": github_repo,
        "tasks": tasks,
        "code": generated_code,
        "repo_url": github_url
    }

    return {
        "session_id": session_id,
        "tasks": tasks,
        "code": generated_code,
        "repo_url": github_url
    }

def refine_code(session_id, suggestion):
    logging.info(f"Refining code for session: {session_id}, suggestion: {suggestion}")

    if session_id not in project_context:
        raise ValueError("Session ID not found")
    if not suggestion or len(suggestion.strip()) < 3:
        raise ValueError("Suggestion must be at least 3 characters long")

    context = project_context[session_id]
    current_code = context["code"]
    github_repo = context["github_repo"]

    refine_task = Task(
        description=f"Refine the following code based on this suggestion: {suggestion}\nCurrent code:\n{current_code}",
        agent=reviewer,
        expected_output="Refined code and comments"
    )

    crew = Crew(agents=[reviewer], tasks=[refine_task])
    result = crew.kickoff()

    refined_code = result.raw if hasattr(result, "raw") else ""

    if not refined_code:
        raise ValueError("No refined code was generated.")

    github_url = github_tool.push_to_repo(github_repo, refined_code, "main.py")

    # Update context
    project_context[session_id]["code"] = refined_code
    project_context[session_id]["repo_url"] = github_url

    return {
        "session_id": session_id,
        "tasks": context["tasks"],
        "code": refined_code,
        "repo_url": github_url
    }

# FastAPI Endpoints
@app.post("/generate-project")
async def generate_project(request: ProjectRequest):
    try:
        session_id = str(uuid.uuid4())
        result = run_macc_agents(request.spec, request.github_repo, session_id)
        logging.info(f"Generated project: {result}")
        return {"status": "success", "result": result}
    except Exception as e:
        logging.error(f"Error in generate_project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/suggest-changes")
async def suggest_changes(request: SuggestionRequest):
    try:
        result = refine_code(request.session_id, request.suggestion)
        logging.info(f"Refined project: {result}")
        return {"status": "success", "result": result}
    except Exception as e:
        logging.error(f"Error in suggest_changes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Run the FastAPI Server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
