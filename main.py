import os
import warnings
import asyncio
import logging
import requests
import subprocess
import uuid
import re
import json
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from github import Github
from crewai_tools import BaseTool

# ---------------- Logging & Environment ----------------
logging.basicConfig(filename="agent_logs.txt", level=logging.INFO)
logging.info("Starting MACC application")

os.environ["PYDANTIC_SKIP_VALIDATING_ASSIGNMENT"] = "1"
warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY not found in .env")
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN not found in .env")

# ---------------- FastAPI Setup ----------------
app = FastAPI(title="MACC - Multi-Agent AI Code Collaborator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint
@app.get("/")
async def root():
    return {"message": "MACC API running - all good"}

# ---------------- Project Context & Queues ----------------
project_context = {}
session_queues = {}

def get_queue(session_id):
    if session_id not in session_queues:
        session_queues[session_id] = asyncio.Queue()
    return session_queues[session_id]

def enqueue(session_id, msg, type="status"):
    q = get_queue(session_id)
    q.put_nowait({"type": type, "message": msg})

# ---------------- Models ----------------
class ProjectRequest(BaseModel):
    spec: str
    github_repo: str = ""  # optional

class SuggestionRequest(BaseModel):
    session_id: str
    suggestion: str

# ---------------- Tools ----------------
class GitHubTool(BaseTool):
    name = "GitHubTool"
    description = "Push code to a GitHub repository"

    def _run(self, repo_name: str, code: str, filename: str) -> str:
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        if not repo_name:
            repo_name = f"{user.login}/{uuid.uuid4().hex[:8]}-macc-project"
        try:
            repo = user.get_repo(repo_name.split("/")[-1])
        except:
            repo = user.create_repo(repo_name.split("/")[-1], auto_init=True)
        try:
            repo.create_file(filename, "Initial commit", code)
        except:
            # If file exists, update
            contents = repo.get_contents(filename)
            repo.update_file(filename, "Update via MACC", code, contents.sha)
        return f"https://github.com/{repo_name}/blob/main/{filename}"

    def push_to_repo(self, repo_name: str, code: str, filename: str) -> str:
        return self._run(repo_name, code, filename)

class WebSearchTool(BaseTool):
    name = "WebSearchTool"
    description = "Search the web for best practices or references"

    def _run(self, query: str) -> str:
        response = requests.get(f"https://api.duckduckgo.com/?q={query}&format=json")
        return response.json().get("Abstract", "No results found")

class CodeExecTool(BaseTool):
    name = "CodeExecTool"
    description = "Execute Python code and return output"

    def _run(self, code: str) -> str:
        with open("temp.py", "w") as f:
            f.write(code)
        result = subprocess.run(["python", "temp.py"], capture_output=True, text=True)
        return result.stdout or result.stderr

github_tool = GitHubTool()
web_search_tool = WebSearchTool()
code_exec_tool = CodeExecTool()

# ---------------- LLM & Agents ----------------
llm = ChatOpenAI(
    model="openrouter/x-ai/grok-4-fast:free",
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    default_headers={"HTTP-Referer": "https://macc-project.streamlit.app", "X-Title": "MACC Project"}
)

planner = Agent(role="Planner", goal="Break down project spec into tasks",
                backstory="Expert in project management and task decomposition.", llm=llm, tools=[web_search_tool])
coder = Agent(role="Coder", goal="Generate clean, functional code",
              backstory="Skilled programmer with expertise in Python and best practices.", llm=llm, tools=[code_exec_tool])
reviewer = Agent(role="Reviewer", goal="Ensure code quality and security, and incorporate user suggestions",
                 backstory="Code quality specialist with deep knowledge of linting, security, and iterative refinement.",
                 llm=llm, tools=[code_exec_tool])

# ---------------- Validation ----------------
def validate_spec(spec: str):
    if not spec or len(spec.strip()) < 3:
        raise ValueError("Project specification must be at least 3 characters long")

# ---------------- Async Streaming ----------------
async def stream_project(session_id, spec, github_repo):
    enqueue(session_id, "Starting project generation...")
    validate_spec(spec)

    g = Github(GITHUB_TOKEN)
    user = g.get_user()
    if not github_repo.strip():
        github_repo = f"{user.login}/{uuid.uuid4().hex[:8]}-macc-project"
        enqueue(session_id, f"Auto-created GitHub repo: {github_repo}")

    # Planner
    enqueue(session_id, "Planner agent: breaking down tasks...")
    plan_task = Task(description=f"Break down spec: {spec}", agent=planner, expected_output="Tasks JSON")
    crew = Crew(agents=[planner], tasks=[plan_task])
    result = crew.kickoff()
    tasks = [task.dict() for task in result.tasks_output] if result.tasks_output else []
    enqueue(session_id, "Planner completed!")

    # Coder
    enqueue(session_id, "Coder agent: generating code...")
    code_task = Task(description="Generate code for the given tasks", agent=coder, expected_output="Python code")
    crew = Crew(agents=[coder], tasks=[code_task])
    result = crew.kickoff()
    code = result.raw if hasattr(result, "raw") else ""
    for line in code.split("\n"):
        enqueue(session_id, line, type="code")
        await asyncio.sleep(0.05)
    enqueue(session_id, "Coder completed code generation!")

    # Reviewer
    enqueue(session_id, "Reviewer agent: reviewing code...")
    review_task = Task(description="Review and improve code", agent=reviewer, expected_output="Refined code")
    crew = Crew(agents=[reviewer], tasks=[review_task])
    result = crew.kickoff()
    refined_code = result.raw if hasattr(result, "raw") else ""
    enqueue(session_id, "Reviewer completed review!")

    # Push to GitHub
    github_url = github_tool.push_to_repo(github_repo, refined_code, "main.py")
    enqueue(session_id, f"Code committed to GitHub: {github_url}")

    # Store context
    project_context[session_id] = {"spec": spec, "github_repo": github_repo, "tasks": tasks, "code": refined_code, "repo_url": github_url}

    # Yield messages
    q = get_queue(session_id)
    while not q.empty():
        msg = await q.get()
        yield json.dumps(msg) + "\n"
        await asyncio.sleep(0.05)

async def stream_suggestion(session_id, suggestion):
    if session_id not in project_context:
        enqueue(session_id, "Session ID not found.")
        return

    context = project_context[session_id]
    code = context["code"]
    github_repo = context["github_repo"]

    enqueue(session_id, f"Applying suggestion: {suggestion}")
    refine_task = Task(description=f"Refine code: {suggestion}\nCurrent code:\n{code}", agent=reviewer,
                       expected_output="Refined code")
    crew = Crew(agents=[reviewer], tasks=[refine_task])
    result = crew.kickoff()
    refined_code = result.raw if hasattr(result, "raw") else ""
    for line in refined_code.split("\n"):
        enqueue(session_id, line, type="code")
        await asyncio.sleep(0.05)
    enqueue(session_id, "Refinement complete!")

    github_url = github_tool.push_to_repo(github_repo, refined_code, "main.py")
    enqueue(session_id, f"Code updated on GitHub: {github_url}")

    project_context[session_id]["code"] = refined_code
    project_context[session_id]["repo_url"] = github_url

    q = get_queue(session_id)
    while not q.empty():
        msg = await q.get()
        yield json.dumps(msg) + "\n"
        await asyncio.sleep(0.05)

# ---------------- Endpoints ----------------
@app.post("/generate-project-stream")
async def generate_project_endpoint(request: ProjectRequest):
    session_id = str(uuid.uuid4())
    return StreamingResponse(stream_project(session_id, request.spec, request.github_repo), media_type="text/event-stream")

@app.post("/suggest-changes-stream")
async def suggest_changes_endpoint(request: SuggestionRequest):
    return StreamingResponse(stream_suggestion(request.session_id, request.suggestion), media_type="text/event-stream")
