# test_macc.py
import os
import sys
import pytest
import asyncio
import time
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from macc.main import llm, graph, safe_slug, GitHubTool

load_dotenv()

# ============================
# Basic LLM Tests
# ============================

def test_llm_returns_text():
    """Test that the LLM can return non-empty text"""
    prompt = "Say hello in one sentence."
    response = llm.call(prompt)
    
    assert response is not None
    assert isinstance(response, str)
    assert len(response.strip()) > 5
    print(f"✅ LLM response: {response[:100]}...")


def test_llm_coding_prompt():
    """Test LLM with a simple coding task"""
    prompt = """Write a short Python function that adds two numbers.
Output ONLY the function code. No explanations."""

    response = llm.call(prompt)
    
    assert response is not None
    assert "def " in response.lower() or "add" in response.lower()
    assert len(response.strip()) > 20
    print(f"✅ Coding prompt worked. First 80 chars: {response[:80]}...")


# ============================
# LangGraph Workflow Tests
# ============================

@pytest.mark.asyncio
async def test_graph_basic_flow():
    """Test the full LangGraph workflow with a simple spec"""
    spec = "Create a Python script that prints 'Hello from MACC' and calculates 5 + 7"

    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: graph.invoke({"spec": spec})
    )

    assert "tasks" in result
    assert "code" in result or "refined_code" in result

    code = result.get("refined_code") or result.get("code", "")
    
    assert isinstance(code, str)
    assert len(code.strip()) > 50, "Code output is too short or empty"
    assert "print" in code.lower() or "hello" in code.lower()

    print("✅ Full LangGraph workflow completed successfully")
    print(f"Code length: {len(code)} characters")


def test_safe_slug():
    """Test the slug generation utility"""
    assert safe_slug("Build a Weather App") == "build-a-weather-app"
    assert safe_slug("Hello World Project!!!") == "hello-world-project"
    assert len(safe_slug("A very long project name that should be truncated because its way too long")) <= 28


# ============================
# Tool Tests
# ============================

def test_github_tool_initialization():
    """Just test that the tool can be instantiated (no real push in test)"""
    tool = GitHubTool()
    assert tool is not None


# ============================
# Performance / Timeout Test
# ============================

@pytest.mark.asyncio
async def test_llm_does_not_hang():
    """Ensure LLM calls have reasonable timeout"""
    start = time.time()
    
    # Use a slightly complex prompt
    prompt = "Write a one-line Python comment explaining what this project does."
    response = llm.call(prompt)
    
    duration = time.time() - start
    
    assert duration < 25, f"LLM call took too long: {duration:.2f}s"
    assert response is not None


if __name__ == "__main__":
    # Run tests directly with python test_macc.py
    test_llm_returns_text()
    test_llm_coding_prompt()
    test_safe_slug()
    test_github_tool_initialization()
    print("\n✅ All basic tests passed!")