# main.py
import os
import warnings
import asyncio
import logging
import requests
import subprocess
import uuid
import re
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from crewai import Agent, Task, Crew
from langchain_openai import ChatOpenAI
from github import Github
from crewai_tools import BaseTool

# --- Logging ---
logging.basicConfig(filename="agent_logs.txt", level=logging.INFO)
logger = logging.getLogger("macc")
logger.info("Starting MACC application")

# --- Minor env & loop fixes ---
os.environ["PYDANTIC_SKIP_VALIDATING_ASSIGNMENT"] = "1"
warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# --- Load env ---
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY not found in .env")
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN not found in .env")

# --- FastAPI setup ---
app = FastAPI(title="MACC - Multi-Agent AI Code Collaborator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # during dev: wildcard; narrow in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- In-memory job store ---
# Structure:
# jobs[job_id] = {
#   "status": "queued|running|done|failed",
#   "logs": [ "log lines" ],
#   "result": {...} or None,
#   "spec": "...",
#   "github_repo": "username/repo" or None,
#   "code": "...",
# }
jobs: Dict[str, Dict[str, Any]] = {}

# --- Request models ---
class ProjectRequest(BaseModel):
    spec: str
    github_repo: Optional[str] = None

class SuggestionRequest(BaseModel):
    session_id: str
    suggestion: str

class CommitRequest(BaseModel):
    job_id: str
    confirm: bool

# --- Tools (same as before) ---
class GitHubTool(BaseTool):
    name: str = "GitHubTool"
    description: str = "Push code to a GitHub repository"

    def _run(self, repo_name: str, code: str, filename: str) -> str:
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        owner = user.login

        # repo_name may be "owner/repo" or just "repo"
        if "/" in repo_name:
            owner_part, repo_part = repo_name.split("/", 1)
            repo_to_use = repo_part
            target_owner = owner_part
        else:
            repo_to_use = repo_name
            target_owner = owner

        # If repo belongs to authenticated user:
        if target_owner == owner:
            try:
                repo = user.get_repo(repo_to_use)
            except Exception:
                repo = user.create_repo(repo_to_use, auto_init=True)
        else:
            # try to access repo under other owner (may fail due to permissions)
            grepo_full = f"{target_owner}/{repo_to_use}"
            try:
                repo = g.get_repo(grepo_full)
            except Exception:
                raise ValueError(f"Unable to access or create repo {grepo_full} with provided token")

        # create or update file
        try:
            contents = repo.get_contents(filename)
            repo.update_file(contents.path, f"Update {filename}", code, contents.sha)
        except Exception:
            repo.create_file(filename, "Initial commit", code)

        return f"https://github.com/{target_owner}/{repo_to_use}/blob/main/{filename}"

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
        result = subprocess.run(["python", "temp.py"], capture_output=True, text=True, timeout=30)
        return result.stdout or result.stderr

# instantiate tools
github_tool = GitHubTool()
web_search_tool = WebSearchTool()
code_exec_tool = CodeExecTool()

# --- LLM setup (same) ---
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

# --- Validators ---
def validate_inputs(spec: str, github_repo: Optional[str]):
    if not spec or len(spec.strip()) < 3:
        raise ValueError("Project specification must be at least 3 characters long")
    if github_repo:
        github_repo = github_repo.strip()
        if github_repo.endswith(".git"):
            github_repo = github_repo[:-4]
        # accept full URLs and normalize to username/repo
        m = re.match(r"^(?:https?://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$", github_repo)
        if not m:
            raise ValueError("GitHub repo must be in the format 'username/repo' or a valid GitHub URL")
        return m.group(1) + "/" + m.group(2)
    return None

# --- Core worker function (runs in background) ---
async def worker_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return
    try:
        job["status"] = "running"
        job["logs"].append("Job started.")
        spec = job["spec"]
        provided_repo = job.get("github_repo")  # may be None

        # Step: Plan
        job["logs"].append("Planner: breaking down spec into tasks...")
        plan_task = Task(
            description=f"Break down this project spec into tasks: {spec}",
            agent=planner,
            expected_output="List of tasks in JSON format"
        )

        # Run planner in thread (blocking SDK)
        planner_result = await asyncio.to_thread(lambda: Crew(agents=[planner], tasks=[plan_task]).kickoff())
        job["logs"].append("Planner finished.")

        # Step: Coding
        job["logs"].append("Coder: generating code...")
        code_task = Task(
            description="Generate code for the given tasks",
            agent=coder,
            expected_output="Python code as a string"
        )
        coder_result = await asyncio.to_thread(lambda: Crew(agents=[coder], tasks=[code_task]).kickoff())
        # try to extract code
        generated_code = ""
        if hasattr(coder_result, "raw") and coder_result.raw:
            generated_code = coder_result.raw
        elif hasattr(coder_result, "tasks_output"):
            # concat outputs
            try:
                generated_code = "\n\n".join([t.get("output", "") for t in coder_result.tasks_output])
            except Exception:
                generated_code = str(coder_result)

        if not generated_code:
            job["logs"].append("Coder produced no code — failing job.")
            raise ValueError("No code generated by coder agent")
        job["code"] = generated_code
        job["logs"].append("Coder finished generating code.")

        # Step: Review
        job["logs"].append("Reviewer: reviewing code...")
        review_task = Task(
            description="Review and improve the generated code",
            agent=reviewer,
            expected_output="Reviewed code and comments"
        )
        reviewer_result = await asyncio.to_thread(lambda: Crew(agents=[reviewer], tasks=[review_task]).kickoff())
        # optionally use reviewer_result to modify code (skipped for simplicity)

        job["logs"].append("Reviewer finished.")

        # Step: Prepare / push to GitHub if repo requested or generate one if not
        # Normalize or create repo name
        if provided_repo:
            repo_name = provided_repo
            job["logs"].append(f"Using provided GitHub repo: {repo_name}")
        else:
            # create new repo name under authenticated user
            gh = Github(GITHUB_TOKEN)
            user = gh.get_user()
            candidate = f"macc-generated-{job_id[:8]}"
            repo_name = f"{user.login}/{candidate}"
            job["logs"].append(f"No repo provided — will create repo: {repo_name}")

        job["logs"].append("Pushing code to GitHub...")
        try:
            github_url = await asyncio.to_thread(lambda: github_tool.push_to_repo(repo_name, job["code"], "main.py"))
            job["repo_url"] = github_url
            job["logs"].append(f"Code pushed: {github_url}")
        except Exception as e:
            job["logs"].append(f"GitHub push error: {str(e)}")
            # do not fail completely — store code and let user download
            job["repo_url"] = None

        # Save final result
        job["result"] = {
            "session_id": job_id,
            "tasks": [],  # for now we don't have structured tasks
            "code": job["code"],
            "repo_url": job.get("repo_url")
        }
        job["status"] = "done"
        job["logs"].append("Job completed successfully.")
    except Exception as e:
        logger.exception("Error in worker_job")
        job["status"] = "failed"
        job["logs"].append(f"Job failed: {str(e)}")
        job["result"] = {"error": str(e)}

# --- Endpoints ---
@app.get("/")
async def root():
    return {"message": "MACC API running - all good"}

@app.post("/generate-project")
async def generate_project(request: ProjectRequest):
    try:
        # validate (normalize) inputs
        normalized_repo = validate_inputs(request.spec, request.github_repo)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # create a new job
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued",
        "logs": [f"Job {job_id} queued."],
        "result": None,
        "spec": request.spec,
        "github_repo": normalized_repo,
        "code": None,
        "repo_url": None,
    }

    # start background task
    asyncio.create_task(worker_job(job_id))

    return {"status": "accepted", "job_id": job_id}

@app.get("/status/{job_id}")
async def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "logs": job["logs"][-50:],  # return recent logs
        "repo_url": job.get("repo_url")
    }

@app.get("/result/{job_id}")
async def job_result(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail=f"Job not ready (status={job['status']})")
    return {"job_id": job_id, "result": job["result"]}

@app.post("/commit")
async def commit_code(req: CommitRequest):
    job_id = req.job_id
    confirm = req.confirm
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job.get("status") != "done":
        raise HTTPException(status_code=400, detail="Job not completed; cannot commit")

    if not confirm:
        return {"status": "cancelled", "detail": "User declined commit"}

    # If repo_url present we can re-push/commit to it (overwrite main.py)
    repo_url = job.get("repo_url")
    if not repo_url:
        # try to create repo now
        gh = Github(GITHUB_TOKEN)
        user = gh.get_user()
        candidate = f"macc-generated-{job_id[:8]}"
        repo_name = f"{user.login}/{candidate}"
    else:
        # extract owner/repo
        m = re.search(r"github\.com/([^/]+/[^/]+)/", repo_url)
        if m:
            repo_name = m.group(1)
        else:
            # fallback to stored job field
            repo_name = job.get("github_repo") or f"{user.login}/macc-generated-{job_id[:8]}"

    try:
        pushed = await asyncio.to_thread(lambda: github_tool.push_to_repo(repo_name, job["code"], "main.py"))
        job["repo_url"] = pushed
        job["logs"].append(f"Committed to GitHub: {pushed}")
        return {"status": "committed", "repo_url": pushed}
    except Exception as e:
        job["logs"].append(f"Commit error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Commit failed: {str(e)}")

@app.post("/suggest-changes")
async def suggest_changes(request: SuggestionRequest):
    # map suggestion to existing job via session_id
    session_id = request.session_id
    if session_id not in jobs:
        raise HTTPException(status_code=404, detail="Session ID not found")
    job = jobs[session_id]
    if not request.suggestion or len(request.suggestion.strip()) < 3:
        raise HTTPException(status_code=400, detail="Suggestion must be at least 3 characters long")

    # Create a small refine job that runs reviewer on existing code
    job["status"] = "running"
    job["logs"].append("Refinement requested by user.")
    try:
        refine_task = Task(
            description=f"Refine the following code based on this suggestion: {request.suggestion}\nCurrent code:\n{job.get('code','')}",
            agent=reviewer,
            expected_output="Refined code and comments"
        )
        result = await asyncio.to_thread(lambda: Crew(agents=[reviewer], tasks=[refine_task]).kickoff())
        refined_code = result.raw if hasattr(result, "raw") else ""
        if not refined_code:
            raise ValueError("No refined code generated")
        job["code"] = refined_code
        job["logs"].append("Refinement complete.")
        job["status"] = "done"
        return {"status": "success", "result": {"session_id": session_id, "code": refined_code, "repo_url": job.get("repo_url")}}
    except Exception as e:
        job["status"] = "failed"
        job["logs"].append(f"Refinement failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Run server (use PORT from env if present)
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
