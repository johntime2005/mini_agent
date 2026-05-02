from __future__ import annotations

import os
import re
from openai import AsyncOpenAI
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file if present

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

SYSTEM_PROMPT = (
    "You are a strict Python code generator. "
    "Given the user's natural language request, you MUST output ONLY valid, "
    "directly runnable Python source code. "
    "Absolutely DO NOT include any Markdown fences such as ```python or ```. "
    "Absolutely DO NOT include any natural language explanation, commentary, "
    "preface, or epilogue. "
    "The entire response MUST be a single Python script that can be saved to "
    "a .py file and executed by the Python interpreter as-is. "
    "If imports are needed, place them at the top. "
    "Do not ask clarifying questions; make reasonable assumptions and output code."
)


class AIServiceError(RuntimeError):
    pass


def _strip_code_fences(text: str) -> str:
    """Defensive cleanup: remove markdown fences if the model disobeyed."""
    text = text.strip()
    fence_pattern = re.compile(r"^```(?:python|py)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)
    match = fence_pattern.match(text)
    if match:
        return match.group(1).strip()
    return text

# 得到ds api
def _get_client() -> AsyncOpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise AIServiceError("Environment variable DEEPSEEK_API_KEY is not set.")
    return AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)


async def generate_python_code(
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
) -> str:
    """Call DeepSeek and return raw Python code (no markdown, no prose)."""
    client = _get_client()
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            stream=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise AIServiceError(f"DeepSeek API call failed: {exc}") from exc

    if not completion.choices:
        raise AIServiceError("DeepSeek API returned no choices.")

    content = completion.choices[0].message.content or ""
    return _strip_code_fences(content)
