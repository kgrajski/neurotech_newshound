"""LLM factory, usage tracking, and invocation helpers."""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.getenv("HOUND_LLM_MODEL", "gpt-4o-mini")
DEFAULT_REVIEWER = os.getenv("HOUND_REVIEWER_MODEL", "")  # Empty = same as model


@dataclass
class UsageTracker:
    """Track LLM API usage and costs."""
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    call_details: List[Dict[str, Any]] = field(default_factory=list)

    PRICING = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    }

    def record(self, model: str, input_tokens: int, output_tokens: int, node: str = ""):
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.calls += 1
        self.call_details.append({
            "node": node, "model": model,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
        })

    def estimate_cost(self, model: str) -> float:
        p = self.PRICING.get(model, {"input": 1.0, "output": 3.0})
        return (self.input_tokens / 1e6) * p["input"] + (self.output_tokens / 1e6) * p["output"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "call_details": self.call_details,
        }


# Global tracker — reset per run
_tracker = UsageTracker()


def get_tracker() -> UsageTracker:
    return _tracker


def reset_tracker():
    global _tracker
    _tracker = UsageTracker()


def create_llm(model: str):
    """Create a LangChain chat model for the given model name."""
    if model.startswith("gpt-"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, temperature=0.3)
    elif model.startswith("gemini-"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, temperature=0.3)
    elif model.startswith("claude-"):
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, temperature=0.3)
    else:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, temperature=0.3)


def invoke_llm(llm, prompt: str, node: str = "", model_name: str = "") -> str:
    """Invoke LLM, track tokens and latency. Returns response content."""
    start = time.time()
    response = llm.invoke(prompt)
    duration_ms = (time.time() - start) * 1000

    usage = getattr(response, "usage_metadata", None)
    if usage:
        in_tok = usage.get("input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)
    else:
        in_tok = len(prompt) // 4
        out_tok = len(response.content) // 4

    _tracker.record(model_name or "unknown", in_tok, out_tok, node)
    return response.content


def parse_json(content: str) -> dict:
    """Extract JSON from LLM response (handles ```json fences)."""
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return json.loads(content)
