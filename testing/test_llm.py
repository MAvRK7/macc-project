import os
import logging
from xml.parsers.expat import model
from dotenv import load_dotenv
from openai import OpenAI
from mistralai.client import Mistral

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

openrouter = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
mistral = Mistral(api_key=MISTRAL_API_KEY)

def test_llm(prompt: str, model: str = "nvidia/nemotron-3-super-120b-a12b:free"):
    print(f"\n=== Testing with model: {model} ===")
    print(f"Prompt: {prompt[:100]}...\n")

    messages = [{"role": "user", "content": prompt}]

    # Test OpenRouter
    try:
        print("→ Calling OpenRouter...")
        # inside test_llm()
        response = openrouter.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=1500,
            extra_headers={
            "HTTP-Referer": "http://localhost",
            "X-Title": "LLM Test Script"
            }
        )
        content = response.choices[0].message.content.strip()
        print("✅ OpenRouter SUCCESS")
        print("Output preview:", content[:500] + "..." if len(content) > 500 else content)
        return content
    except Exception as e:
        print(f"❌ OpenRouter failed: {e}")

    # Test Mistral fallback
    try:
        print("\n→ Falling back to Mistral...")
        res = mistral.chat.complete(
            model="mistral-small-latest",
            messages=messages,
            temperature=0.2,
        )
        content = res.choices[0].message.content.strip()
        print("✅ Mistral SUCCESS")
        print("Output preview:", content[:500] + "..." if len(content) > 500 else content)
        return content
    except Exception as e:
        print(f"❌ Mistral also failed: {e}")

    print("❌ Both providers failed")
    return None

# ================== Test Cases ==================
if __name__ == "__main__":
    test_prompt = """Write a complete, production-ready, SINGLE-FILE Python script that prints a multiplication table for a number entered by the user.

Rules:
- One file only
- Proper imports at top
- Full error handling
- Include if __name__ == '__main__': 
- Output ONLY the full Python code. No explanations."""

    result = test_llm(test_prompt, model="nvidia/nemotron-3-super-120b-a12b:free")

    if result and "def " in result:
        print("\n🎉 LLM is working correctly!")
    else:
        print("\n⚠️ LLM is still failing. Try a different model.")