# main.py
import os
import warnings
import asyncio
import logging
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from github import Github

# CrewAI / LLM imports (assumed installed)
from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from crewai_tools import BaseTool

# ---------------- Logging & env ----------------
logging.basicConfig(level=logging.INFO, filename="agent_logs.txt")
logging.info("Starting MACC application")

os.environ["PYDANTIC_SKIP_VALIDATING_ASSIGNMENT"] = "1"
warnings.filterwarnings("ignore", category=DeprecationWarning)

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY missing in environment")
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN missing in environment")

# ---------------- FastAPI ----------------
app = FastAPI(title="MACC - Multi-Agent AI Code Collaborator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- In-memory state ----------------
# session_id -> list[dict] of messages (message consumed on GET /updates)
session_messages: Dict[str, list] = {}
# session_id -> final context (spec, code, readme, repo name/url)
project_context: Dict[str, Dict[str, Any]] = {}
# sentinel for finished sessions
session_done: Dict[str, bool] = {}

# executor for blocking Crew calls
executor = ThreadPoolExecutor(max_workers=3)

# ---------------- Models ----------------
class ProjectRequest(BaseModel):
    spec: str
    github_repo: Optional[str] = ""

class SuggestionRequest(BaseModel):
    session_id: str
    suggestion: str

class CommitRequest(BaseModel):
    session_id: str

# ---------------- Utility helpers ----------------
def safe_slug(text: str, max_len: int = 28) -> str:
    """Create a safe repo name from the spec (lowercase, alnum + hyphen)."""
    s = text.lower()
    # keep alnum and spaces
    s = "".join(c if c.isalnum() or c.isspace() else " " for c in s)
    s = "-".join(s.split())
    s = s.strip("-")
    if not s:
        s = "macc-project"
    return (s[:max_len]).rstrip("-")

def ensure_session(session_id: str):
    if session_id not in session_messages:
        session_messages[session_id] = []
    if session_id not in session_done:
        session_done[session_id] = False
    if session_id not in project_context:
        project_context[session_id] = {}

def enqueue_message(session_id: str, typ: str, message: str):
    """Append a message to session message list (for polling)."""
    ensure_session(session_id)
    session_messages[session_id].append({"type": typ, "message": message})

def drain_messages(session_id: str) -> list:
    """Return accumulated messages and clear them."""
    ensure_session(session_id)
    msgs = session_messages[session_id][:]
    session_messages[session_id] = []
    return msgs

# ---------------- Tools (Pydantic safe) ----------------
class GitHubTool(BaseTool):
    name: str = "GitHubTool"
    description: str = "Push code and README to GitHub"

    def _run(self, *args, **kwargs):
        raise NotImplementedError("Use push()")

    def push(self, repo_name: str, code: str, filename: str = "main.py", readme: Optional[str] = None) -> str:
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        # if repo_name is "username/repo" or "repo"
        if "/" in repo_name:
            _, short = repo_name.split("/", 1)
            repo_short = short
        else:
            repo_short = repo_name
        try:
            repo = user.get_repo(repo_short)
        except Exception:
            repo = user.create_repo(repo_short, auto_init=True)
        # create or update main file
        try:
            repo.create_file(filename, "Add main code", code)
        except Exception:
            try:
                existing = repo.get_contents(filename)
                repo.update_file(filename, "Update main code", code, existing.sha)
            except Exception:
                pass
        # README
        if readme:
            try:
                repo.create_file("README.md", "Add README", readme)
            except Exception:
                try:
                    existing = repo.get_contents("README.md")
                    repo.update_file("README.md", "Update README", readme, existing.sha)
                except Exception:
                    pass
        return f"https://github.com/{user.login}/{repo_short}/blob/main/{filename}"

class CodeExecTool(BaseTool):
    name: str = "CodeExecTool"
    description: str = "Execute Python code briefly"

    def _run(self, code: str) -> str:
        import subprocess, tempfile
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".py") as f:
                f.write(code)
                fname = f.name
            proc = subprocess.run(["python", fname], capture_output=True, text=True, timeout=4)
            return proc.stdout or proc.stderr or ""
        except Exception as e:
            return f"Execution error: {e}"

github_tool = GitHubTool()
code_exec_tool = CodeExecTool()

# ---------------- LLM & agents ----------------
llm = ChatOpenAI(
    model="openrouter/x-ai/grok-4-fast:free",
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

planner = Agent(role="Planner", goal="Break down project spec into tasks", backstory="Planner", llm=llm)
coder = Agent(role="Coder", goal="Generate high-quality Python code", backstory="Coder", llm=llm, tools=[code_exec_tool])
reviewer = Agent(role="Reviewer", goal="Review and improve code", backstory="Reviewer", llm=llm, tools=[code_exec_tool])

# Crew kickoff wrapper (blocking) for executor
def run_crew(agents, tasks):
    crew = Crew(agents=agents, tasks=tasks)
    return crew.kickoff()

# ---------------- Background tasks ----------------
async def generate_background(session_id: str, spec: str, github_repo: Optional[str]):
    ensure_session(session_id)
    try:
        enqueue_message(session_id, "status", "Starting project generation...")
        if not spec or len(spec.strip()) < 3:
            enqueue_message(session_id, "status", "Error: Project spec too short.")
            session_done[session_id] = True
            return

        # derive repo name from prompt if not provided
        if github_repo and github_repo.strip():
            repo = github_repo.strip()
            enqueue_message(session_id, "status", f"Using provided GitHub repo: {repo}")
        else:
            slug = safe_slug(spec)
            # ensure uniqueness by appending short UUID
            repo = f"{slug}-{uuid.uuid4().hex[:6]}"
            # store repo as username/repo? We'll let GitHubTool use user's login later.
            enqueue_message(session_id, "status", f"Auto-generated repo name: {repo}")

        # PLANNER (run in thread)
        enqueue_message(session_id, "status", "Planner: breaking down tasks...")
        plan_task = Task(description=f"Break down: {spec}", agent=planner, expected_output="tasks")
        loop = asyncio.get_event_loop()
        try:
            plan_res = await loop.run_in_executor(executor, partial(run_crew, [planner], [plan_task]))
            tasks_out = [t.dict() for t in getattr(plan_res, "tasks_output", [])] if getattr(plan_res, "tasks_output", None) else []
        except Exception as e:
            enqueue_message(session_id, "status", f"Planner failed: {e}")
            tasks_out = []
        enqueue_message(session_id, "status", "Planner completed.")

        # CODER (run in thread)
        enqueue_message(session_id, "status", "Coder: generating code...")
        code_task = Task(description=f"Generate production-quality Python code: {spec}", agent=coder, expected_output="python_code")
        try:
            code_res = await loop.run_in_executor(executor, partial(run_crew, [coder], [code_task]))
            generated = getattr(code_res, "raw", "") or ""
        except Exception as e:
            enqueue_message(session_id, "status", f"Coder failed: {e}")
            generated = ""

        if not generated.strip():
            # fallback placeholder
            generated = (
                "# Placeholder Python code — coder produced empty output\n"
                "def main():\n"
                "    print('Hello from MACC placeholder')\n\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            )
            enqueue_message(session_id, "status", "Coder returned empty output; using placeholder.")

        # stream code lines as messages
        for ln in generated.splitlines():
            enqueue_message(session_id, "code", ln)
        enqueue_message(session_id, "status", "Coder completed generation.")

        # REVIEWER (run in thread)
        enqueue_message(session_id, "status", "Reviewer: reviewing code...")
        review_task = Task(description=f"Review and improve the code:\n{generated}", agent=reviewer, expected_output="refined_code")
        try:
            review_res = await loop.run_in_executor(executor, partial(run_crew, [reviewer], [review_task]))
            refined = getattr(review_res, "raw", "") or generated
        except Exception as e:
            enqueue_message(session_id, "status", f"Reviewer failed: {e}")
            refined = generated

        # stream refined code lines
        enqueue_message(session_id, "status", "Reviewer completed review; streaming refined code...")
        for ln in refined.splitlines():
            enqueue_message(session_id, "code", ln)

        # generate short README (deterministic)
        readme = f"# {repo}\n\n{spec}\n\nGenerated by MACC - Multi-Agent Code Collaborator\n"
        # store context
        project_context[session_id] = {
            "spec": spec,
            "github_repo": repo,
            "tasks": tasks_out,
            "code": refined,
            "readme": readme,
            "repo_url": None,
        }

        enqueue_message(session_id, "status", f"Project ready. Repo to use: {repo}")
        session_done[session_id] = True
    except Exception as e:
        logging.exception("generate_background error")
        enqueue_message(session_id, "status", f"Unhandled error: {e}")
        session_done[session_id] = True

async def refine_background(session_id: str, suggestion: str):
    ensure_session(session_id)
    try:
        if session_id not in project_context:
            enqueue_message(session_id, "status", "Error: session not found for refinement.")
            session_done[session_id] = True
            return
        ctx = project_context[session_id]
        current_code = ctx.get("code", "")
        enqueue_message(session_id, "status", f"Applying suggestion: {suggestion}")
        review_task = Task(description=f"Refine code based on: {suggestion}\n\nCurrent code:\n{current_code}", agent=reviewer, expected_output="refined_code")
        loop = asyncio.get_event_loop()
        try:
            review_res = await loop.run_in_executor(executor, partial(run_crew, [reviewer], [review_task]))
            refined = getattr(review_res, "raw", "") or current_code
        except Exception as e:
            enqueue_message(session_id, "status", f"Refinement failed: {e}")
            refined = current_code

        ctx["code"] = refined
        # stream refined code
        for ln in refined.splitlines():
            enqueue_message(session_id, "code", ln)
        enqueue_message(session_id, "status", "Refinement applied.")
        session_done[session_id] = True
    except Exception as e:
        logging.exception("refine_background error")
        enqueue_message(session_id, "status", f"Unhandled error: {e}")
        session_done[session_id] = True

# ---------------- API endpoints ----------------

@app.post("/generate-project")
async def generate_project(req: ProjectRequest):
    """Start generation in background and immediately return session_id."""
    session_id = str(uuid.uuid4())
    # initialize
    ensure_session(session_id)
    session_done[session_id] = False
    # start background
    asyncio.create_task(generate_background(session_id, req.spec, req.github_repo))
    return {"session_id": session_id}

@app.get("/updates/{session_id}")
async def get_updates(session_id: str):
    """Return queued messages (and done flag) for session; clears returned messages."""
    ensure_session(session_id)
    msgs = drain_messages(session_id)
    done = session_done.get(session_id, False)
    # include repo_url if available
    repo_url = project_context.get(session_id, {}).get("repo_url")
    return {"messages": msgs, "done": done, "repo_url": repo_url}

@app.post("/suggest-changes")
async def suggest_changes(req: SuggestionRequest):
    """Start refinement (background) and return session_id (same)."""
    if req.session_id not in session_messages and req.session_id not in project_context:
        raise HTTPException(status_code=404, detail="Session not found")
    ensure_session(req.session_id)
    session_done[req.session_id] = False
    asyncio.create_task(refine_background(req.session_id, req.suggestion))
    return {"session_id": req.session_id}

@app.post("/commit")
async def commit(req: CommitRequest):
    sid = req.session_id
    if sid not in project_context:
        raise HTTPException(status_code=404, detail="Session not found")
    ctx = project_context[sid]
    repo_name = ctx.get("github_repo")
    code = ctx.get("code", "")
    readme = ctx.get("readme", "")
    if not repo_name:
        raise HTTPException(status_code=400, detail="No repo name in session")
    try:
        url = github_tool.push(repo_name, code, filename="main.py", readme=readme)
        ctx["repo_url"] = url
        enqueue_message(sid, "status", f"Code committed to GitHub: {url}")
        return {"status": "committed", "repo_url": url}
    except Exception as e:
        logging.exception("commit failed")
        raise HTTPException(status_code=500, detail=f"GitHub commit failed: {e}")

@app.get("/")
async def root():
    return JSONResponse({"message": "MACC API running - all good"})

# ---------------- Run if main ----------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
