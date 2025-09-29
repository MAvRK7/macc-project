import os
import warnings
import asyncio
import logging
import requests
import subprocess
import uuid
import re
import json
import time
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://macc-project.streamlit.app", "http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint
@app.get("/")
async def root():
    return {"message": "MACC API running - all good"}

# Project context storage (in-memory)
project_context = {}

# In-memory queue per session for status updates
session_queues = {}

def enqueue_status(session_id, msg):
    if session_id not in session_queues:
        session_queues[session_id] = asyncio.Queue()
    session_queues[session_id].put_nowait(msg)

# Request models
class ProjectRequest(BaseModel):
    spec: str
    github_repo: str = None  # Optional

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
        try:
            repo.create_file(filename, "Initial commit", code)
        except:
            # If file exists, update
            contents = repo.get_contents(filename)
            repo.update_file(contents.path, "Update via MACC", code, contents.sha)
        return f"https://github.com/{repo_name}/blob/main/{filename}"

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
llm = ChatOpenAI(
    model="openrouter/x-ai/grok-4-fast:free",
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    default_headers={
        "HTTP-Referer": "https://macc-project.streamlit.app",
        "X-Title": "MACC Project"
    }
)

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
def validate_inputs(spec: str):
    if not spec or len(spec.strip()) < 3:
        raise ValueError("Project specification must be at least 3 characters long")

# Stream generator for project generation with status updates
async def stream_generator(session_id, spec, github_repo):
    try:
        # Step 0: validate inputs
        enqueue_status(session_id, "Starting project generation...")
        validate_inputs(spec)
        enqueue_status(session_id, "Validation completed!")

        # Step 1: auto-generate GitHub repo if not provided
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        if not github_repo or github_repo.strip() == "":
            github_repo = f"{user.login}/{uuid.uuid4().hex[:8]}-macc-project"
            enqueue_status(session_id, f"Auto-created GitHub repo: {github_repo}")

        # Step 2: Planner
        enqueue_status(session_id, "Planner agent: breaking down tasks...")
        plan_task = Task(
            description=f"Break down this project spec into tasks: {spec}",
            agent=planner,
            expected_output="List of tasks in JSON format"
        )
        crew = Crew(agents=[planner], tasks=[plan_task])
        result = crew.kickoff()
        tasks = [task.dict() for task in result.tasks_output] if result.tasks_output else []
        enqueue_status(session_id, "Planner agent completed tasks!")

        # Step 3: Coder
        enqueue_status(session_id, "Coder agent: generating code...")
        code_task = Task(
            description="Generate code for the given tasks",
            agent=coder,
            expected_output="Python code as a string"
        )
        crew = Crew(agents=[coder], tasks=[code_task])
        result = crew.kickoff()
        generated_code = result.raw if hasattr(result, "raw") else ""
        enqueue_status(session_id, "Coder agent completed code generation!")

        # Step 4: Reviewer
        enqueue_status(session_id, "Reviewer agent: reviewing code...")
        review_task = Task(
            description="Review and improve the generated code",
            agent=reviewer,
            expected_output="Reviewed code and comments"
        )
        crew = Crew(agents=[reviewer], tasks=[review_task])
        result = crew.kickoff()
        refined_code = result.raw if hasattr(result, "raw") else ""
        enqueue_status(session_id, "Reviewer agent completed review!")

        # Step 5: Push to GitHub
        github_url = github_tool.push_to_repo(github_repo, refined_code, "main.py")
        enqueue_status(session_id, f"Code committed to GitHub: {github_url}")

        # Step 6: Store context
        project_context[session_id] = {
            "spec": spec,
            "github_repo": github_repo,
            "tasks": tasks,
            "code": refined_code,
            "repo_url": github_url
        }
        enqueue_status(session_id, "Project generation completed!")

        # Yield all messages in queue
        q = session_queues[session_id]
        while not q.empty():
            msg = await q.get()
            yield json.dumps({"status": msg}) + "\n"
            await asyncio.sleep(0.1)

    except Exception as e:
        yield json.dumps({"error": str(e)}) + "\n"

# Non-streaming version (if needed)
def run_macc_agents(spec, github_repo, session_id, status_callback=None):
    validate_inputs(spec)

    # Optional GitHub repo auto-generation
    g = Github(GITHUB_TOKEN)
    user = g.get_user()
    if not github_repo or github_repo.strip() == "":
        github_repo = f"{user.login}/{uuid.uuid4().hex[:8]}-macc-project"
        if status_callback:
            status_callback(f"Auto-created GitHub repo: {github_repo}")

    if status_callback:
        status_callback("Planner agent: breaking down tasks...")
    plan_task = Task(
        description=f"Break down this project spec into tasks: {spec}",
        agent=planner,
        expected_output="List of tasks in JSON format"
    )

    if status_callback:
        status_callback("Coder agent: generating code...")
    code_task = Task(
        description="Generate code for the given tasks",
        agent=coder,
        expected_output="Python code as a string"
    )

    if status_callback:
        status_callback("Reviewer agent: reviewing code...")
    review_task = Task(
        description="Review and improve the generated code",
        agent=reviewer,
        expected_output="Reviewed code and comments"
    )

    crew = Crew(agents=[planner, coder, reviewer], tasks=[plan_task, code_task, review_task])
    result = crew.kickoff()

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

def refine_code(session_id, suggestion, status_callback=None):
    if session_id not in project_context:
        raise ValueError("Session ID not found")
    if not suggestion or len(suggestion.strip()) < 3:
        raise ValueError("Suggestion must be at least 3 characters long")

    context = project_context[session_id]
    current_code = context["code"]
    github_repo = context["github_repo"]

    if status_callback:
        status_callback("Reviewer agent: refining code based on suggestion...")

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
        return {"status": "success", "result": result}
    except Exception as e:
        logging.error(f"Error in generate_project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-project-stream")
async def generate_project_stream(request: ProjectRequest):
    session_id = str(uuid.uuid4())
    return StreamingResponse(
        stream_generator(session_id, request.spec, request.github_repo),
        media_type="application/json",
    )

@app.post("/suggest-changes")
async def suggest_changes(request: SuggestionRequest):
    try:
        result = refine_code(request.session_id, request.suggestion)
        return {"status": "success", "result": result}
    except Exception as e:
        logging.error(f"Error in suggest_changes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
