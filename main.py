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
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from github import Github

# CrewAI / LLM imports (assumed installed and configured)
from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from crewai_tools import BaseTool

# ---------------- Logging & Environment ----------------
logging.basicConfig(level=logging.INFO, filename="agent_logs.txt")
logging.info("Starting MACC application")

# Pydantic assignment skip (keeps older behavior where needed)
os.environ["PYDANTIC_SKIP_VALIDATING_ASSIGNMENT"] = "1"
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Load .env
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY not found in environment")
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN not found in environment")

# ---------------- FastAPI Setup ----------------
app = FastAPI(title="MACC - Multi-Agent AI Code Collaborator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- In-memory session state ----------------
# session_id -> asyncio.Queue of messages (dict with type+message)
session_queues: Dict[str, asyncio.Queue] = {}
# session context: store spec, repo, code, readme, repo_url, tasks
project_context: Dict[str, Dict[str, Any]] = {}

# Executor for blocking work (Crew.kickoff may be blocking)
executor = ThreadPoolExecutor(max_workers=4)

# ---------------- Helper functions ----------------
def get_queue(session_id: str) -> asyncio.Queue:
    q = session_queues.get(session_id)
    if q is None:
        q = asyncio.Queue()
        session_queues[session_id] = q
    return q

def enqueue(session_id: str, message: str, typ: str = "status") -> None:
    """Put a message into a session queue. Non-blocking."""
    q = get_queue(session_id)
    q.put_nowait({"type": typ, "message": message})

async def stream_from_queue(session_id: str):
    """Async generator used by StreamingResponse to stream messages as JSON lines."""
    q = get_queue(session_id)
    # Keep streaming until a special 'DONE' status is enqueued or queue is empty and producer done.
    while True:
        try:
            msg = await q.get()
        except asyncio.CancelledError:
            break
        if msg is None:
            # sentinel to end stream
            break
        yield json.dumps(msg) + "\n"
        # small sleep to give client time to process without tight CPU loop
        await asyncio.sleep(0.01)
        # If producer has put a final DONE message we can break (but still allow any remaining messages)
        if msg.get("type") == "status" and msg.get("message") == "__MACC_DONE__":
            break

# ---------------- Models ----------------
class ProjectRequest(BaseModel):
    spec: str
    github_repo: Optional[str] = ""

class SuggestionRequest(BaseModel):
    session_id: str
    suggestion: str

class CommitRequest(BaseModel):
    session_id: str

# ---------------- Tools (Pydantic-safe annotations) ----------------
class GitHubTool(BaseTool):
    name: str = "GitHubTool"
    description: str = "Push code and README to a GitHub repository"

    # BaseTool requires _run; implement a stub pointing to push
    def _run(self, *args, **kwargs):
        raise NotImplementedError("Use push() method for programmatic pushes")

    def push(self, repo_name: str, code: str, filename: str = "main.py", readme: Optional[str] = None) -> str:
        """Create or update repository and push code + README. Returns URL to main file."""
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        # repo_name expected format "username/repo" or "repo" -> interpret as user's repo
        if "/" in repo_name:
            owner, short = repo_name.split("/", 1)
            repo_short_name = short
        else:
            repo_short_name = repo_name
        try:
            repo = user.get_repo(repo_short_name)
            repo_exists = True
        except Exception:
            repo = user.create_repo(repo_short_name, auto_init=True)
            repo_exists = False

        # Create or update main file
        try:
            repo.create_file(filename, "Add main code", code)
        except Exception as e:
            # If file exists update it
            try:
                existing = repo.get_contents(filename)
                repo.update_file(filename, "Update main code via MACC", code, existing.sha)
            except Exception as e2:
                # fallback: raise
                raise

        # README
        if readme:
            try:
                repo.create_file("README.md", "Add README", readme)
            except Exception:
                try:
                    existing = repo.get_contents("README.md")
                    repo.update_file("README.md", "Update README via MACC", readme, existing.sha)
                except Exception:
                    # ignore
                    pass

        return f"https://github.com/{user.login}/{repo_short_name}/blob/main/{filename}"

class CodeExecTool(BaseTool):
    name: str = "CodeExecTool"
    description: str = "Execute Python code (sandboxed minimal run)"

    def _run(self, code: str) -> str:
        """Execute code in a temporary file and capture stdout/stderr. Keep small/time-limited."""
        import subprocess, tempfile
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".py") as f:
                f.write(code)
                fname = f.name
            # run with timeout to avoid long computations
            proc = subprocess.run(["python", fname], capture_output=True, text=True, timeout=5)
            out = proc.stdout or proc.stderr or ""
            return out
        except Exception as e:
            return f"Execution error: {str(e)}"

# instantiate tools
github_tool = GitHubTool()
code_exec_tool = CodeExecTool()

# ---------------- LLM & Agents ----------------
# Create LLM wrapper for agents
llm = ChatOpenAI(
    model="openrouter/x-ai/grok-4-fast:free",
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

planner = Agent(role="Planner", goal="Break down project spec into tasks", backstory="Planner", llm=llm)
coder = Agent(role="Coder", goal="Generate code", backstory="Python coder", llm=llm, tools=[code_exec_tool])
reviewer = Agent(role="Reviewer", goal="Review and improve code", backstory="Reviewer", llm=llm, tools=[code_exec_tool])

# ---------------- Blocking Crew kickoff wrapper ----------------
def run_crew_kickoff(agents, tasks):
    """Wrapper to call Crew(...).kickoff() in a thread executor because it can block."""
    crew = Crew(agents=agents, tasks=tasks)
    result = crew.kickoff()
    return result

# ---------------- Core generation logic (background task) ----------------
async def generate_project_background(session_id: str, spec: str, github_repo: Optional[str]):
    """
    Background coroutine which runs heavy tasks in executor and enqueues status/code messages.
    """
    try:
        enqueue(session_id, "Starting project generation...", "status")
        # Basic validation
        if not spec or len(spec.strip()) < 3:
            enqueue(session_id, "Error: Project spec must be at least 3 characters", "status")
            enqueue(session_id, "__MACC_DONE__", "status")
            return

        # Prepare repo name
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        if not github_repo or not github_repo.strip():
            # make a repo name but do NOT create it now; commit will create/update on demand
            repo_name = f"{user.login}/{uuid.uuid4().hex[:8]}-macc-project"
            enqueue(session_id, f"Auto-generated GitHub repo name: {repo_name}", "status")
        else:
            repo_name = github_repo.strip()
            enqueue(session_id, f"Using provided GitHub repo: {repo_name}", "status")

        # Planner (run in executor)
        enqueue(session_id, "Planner: breaking down tasks...", "status")
        plan_task = Task(description=f"Break down this project spec into tasks: {spec}", agent=planner, expected_output="tasks JSON")
        loop = asyncio.get_event_loop()
        try:
            plan_result = await loop.run_in_executor(executor, partial(run_crew_kickoff, [planner], [plan_task]))
        except Exception as e:
            enqueue(session_id, f"Planner failed: {str(e)}", "status")
            enqueue(session_id, "__MACC_DONE__", "status")
            return
        tasks_list = []
        try:
            tasks_list = [t.dict() for t in plan_result.tasks_output] if getattr(plan_result, "tasks_output", None) else []
        except Exception:
            tasks_list = []
        enqueue(session_id, "Planner completed.", "status")

        # Coder (generate code). Use executor for blocking call.
        enqueue(session_id, "Coder: generating code...", "status")
        code_task = Task(description=f"Generate production-quality Python code for the spec: {spec}", agent=coder, expected_output="Python code")
        try:
            code_result = await loop.run_in_executor(executor, partial(run_crew_kickoff, [coder], [code_task]))
        except Exception as e:
            enqueue(session_id, f"Coder failed: {str(e)}", "status")
            enqueue(session_id, "__MACC_DONE__", "status")
            return

        generated_code = ""
        try:
            generated_code = getattr(code_result, "raw", "") or ""
        except Exception:
            generated_code = ""

        if not generated_code.strip():
            # If model returned empty, provide a safe placeholder but flag to reviewer
            placeholder = (
                "# Placeholder code: the coder agent returned no code.\n"
                "# Please try refining the prompt or press 'Suggest changes'.\n"
                "def main():\n"
                "    print('Hello from MACC placeholder')\n\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            )
            generated_code = placeholder
            enqueue(session_id, "Coder returned empty output; using placeholder code.", "status")

        # Stream generated code line-by-line
        for ln in generated_code.splitlines():
            enqueue(session_id, ln, "code")
            # small sleep to pace the stream to the client
            await asyncio.sleep(0.01)
        enqueue(session_id, "Coder generation completed.", "status")

        # Reviewer (refine)
        enqueue(session_id, "Reviewer: reviewing and improving code...", "status")
        review_task = Task(description=f"Review and improve the following code:\n{generated_code}", agent=reviewer, expected_output="Refined code")
        try:
            review_result = await loop.run_in_executor(executor, partial(run_crew_kickoff, [reviewer], [review_task]))
        except Exception as e:
            enqueue(session_id, f"Reviewer failed: {str(e)}", "status")
            # still allow commit of generated_code
            refined_code = generated_code
        else:
            refined_code = getattr(review_result, "raw", "") or generated_code

        # If reviewer returned nothing, keep generated_code
        if not refined_code.strip():
            refined_code = generated_code
            enqueue(session_id, "Reviewer produced no output; keeping original generated code.", "status")

        # Stream refined code (so frontend receives final/clean code)
        enqueue(session_id, "Streaming final refined code...", "status")
        for ln in refined_code.splitlines():
            enqueue(session_id, ln, "code")
            await asyncio.sleep(0.005)

        # Generate a short description/README text (simple deterministic text based on spec)
        readme_text = f"# {repo_name.split('/')[-1]}\n\n{spec}\n\nGenerated with MACC - Multi-Agent Code Collaborator.\n"
        enqueue(session_id, "Generated README/description.", "status")
        # store context (do not commit yet)
        project_context[session_id] = {
            "spec": spec,
            "github_repo": repo_name,
            "tasks": tasks_list,
            "code": refined_code,
            "readme": readme_text,
            "repo_url": None,
        }

        enqueue(session_id, "Project generation completed. Ready to commit on user confirmation.", "status")
        # sentinel to indicate done — client may stop listening after it sees this
        enqueue(session_id, "__MACC_DONE__", "status")
    except Exception as e:
        logging.exception("Unhandled error in generate_project_background")
        enqueue(session_id, f"Unhandled error: {str(e)}", "status")
        enqueue(session_id, "__MACC_DONE__", "status")

# ---------------- Suggestion logic (background) ----------------
async def refine_project_background(session_id: str, suggestion: str):
    try:
        if session_id not in project_context:
            enqueue(session_id, "Session not found. Can't apply suggestion.", "status")
            enqueue(session_id, "__MACC_DONE__", "status")
            return

        ctx = project_context[session_id]
        current_code = ctx.get("code", "")
        enqueue(session_id, f"Applying suggestion: {suggestion}", "status")

        # run reviewer with suggestion in executor
        review_task = Task(description=f"Refine this code according to suggestion: {suggestion}\n\nCurrent code:\n{current_code}", agent=reviewer, expected_output="Refined code")
        loop = asyncio.get_event_loop()
        try:
            review_result = await loop.run_in_executor(executor, partial(run_crew_kickoff, [reviewer], [review_task]))
            new_code = getattr(review_result, "raw", "") or current_code
        except Exception as e:
            enqueue(session_id, f"Reviewer failed: {str(e)}", "status")
            new_code = current_code

        # update context and stream new code
        ctx["code"] = new_code
        enqueue(session_id, "Refinement complete. Streaming updated code...", "status")
        for ln in new_code.splitlines():
            enqueue(session_id, ln, "code")
            await asyncio.sleep(0.005)

        enqueue(session_id, "Suggestion applied.", "status")
        enqueue(session_id, "__MACC_DONE__", "status")
    except Exception as e:
        logging.exception("Unhandled error in refine_project_background")
        enqueue(session_id, f"Unhandled error: {str(e)}", "status")
        enqueue(session_id, "__MACC_DONE__", "status")

# ---------------- API Endpoints ----------------

@app.post("/generate-project")  # legacy simple quick-start: returns session id and starts background
async def start_project(request: ProjectRequest):
    session_id = str(uuid.uuid4())
    # create empty queue/context
    get_queue(session_id)
    project_context[session_id] = {"spec": request.spec, "github_repo": request.github_repo or "", "code": "", "readme": "", "repo_url": None, "tasks": []}
    # start background task (no await)
    asyncio.create_task(generate_project_background(session_id, request.spec, request.github_repo))
    return {"session_id": session_id}

@app.post("/generate-project-stream")
async def generate_project_stream_endpoint(request: ProjectRequest):
    """
    Convenience endpoint: starts background job and returns a streaming response of queue messages.
    The client can POST and consume the stream immediately.
    """
    session_id = str(uuid.uuid4())
    # ensure queue exists
    get_queue(session_id)
    # start background process
    asyncio.create_task(generate_project_background(session_id, request.spec, request.github_repo))
    # return streaming response — this will stream messages as they are enqueued
    return StreamingResponse(stream_from_queue(session_id), media_type="application/json")

@app.get("/stream/{session_id}")
async def stream_session(session_id: str):
    """Client can connect to this endpoint to receive queued messages for a session."""
    if session_id not in session_queues:
        # If session unknown, create empty queue so client can still connect
        get_queue(session_id)
    return StreamingResponse(stream_from_queue(session_id), media_type="application/json")

@app.post("/suggest-changes")
async def suggest_changes(request: SuggestionRequest):
    if request.session_id not in session_queues and request.session_id not in project_context:
        raise HTTPException(status_code=404, detail="Session not found")
    # start background refinement
    get_queue(request.session_id)
    asyncio.create_task(refine_project_background(request.session_id, request.suggestion))
    return {"status": "started", "session_id": request.session_id}

@app.post("/suggest-changes-stream")
async def suggest_changes_stream(request: SuggestionRequest):
    """Start the refine background job and return a streaming response of its queue messages."""
    if request.session_id not in project_context:
        raise HTTPException(status_code=404, detail="Session not found")
    # start background refine
    asyncio.create_task(refine_project_background(request.session_id, request.suggestion))
    return StreamingResponse(stream_from_queue(request.session_id), media_type="application/json")

@app.post("/commit")
async def commit_project(req: CommitRequest):
    """
    Commit code and README to GitHub. This is performed only when user confirms.
    """
    sid = req.session_id
    if sid not in project_context:
        raise HTTPException(status_code=404, detail="Session not found")
    ctx = project_context[sid]
    repo_name = ctx.get("github_repo")
    code = ctx.get("code", "")
    readme = ctx.get("readme", "")
    if not repo_name:
        raise HTTPException(status_code=400, detail="No repo name available in session")
    try:
        url = github_tool.push(repo_name, code, filename="main.py", readme=readme)
    except Exception as e:
        logging.exception("Failed to push to GitHub")
        raise HTTPException(status_code=500, detail=f"GitHub push failed: {str(e)}")
    ctx["repo_url"] = url
    enqueue(sid, f"Code committed to GitHub: {url}", "status")
    # signal done to any stream listeners
    enqueue(sid, "__MACC_DONE__", "status")
    return {"status": "committed", "repo_url": url}

@app.get("/")
async def root():
    return {"message": "MACC API running - all good"}

# ---------------- Run with port for Render ----------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
