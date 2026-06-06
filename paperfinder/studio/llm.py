"""Single completion seam for studio generators.

Local-first: by default this calls the same OpenAI-compatible endpoint paper-finder
already uses for reference stripping (Ollama at PAPERFINDER_LLM_URL). Pass
frontier=True to route to Anthropic (Sonnet/Opus) for higher-fidelity synthesis.

No new dependencies: both paths use urllib.

Env:
  PAPERFINDER_LLM_URL        OpenAI-compatible base URL (default http://localhost:11434/v1)
  PAPERFINDER_LLM_MODEL      local model tag (default llama3.1:8b)
  PAPERFINDER_FRONTIER_MODEL frontier model id (default claude-sonnet-4-6)
  ANTHROPIC_API_KEY          required only when frontier=True
"""

import json
import os
import urllib.request

LLM_URL = os.environ.get("PAPERFINDER_LLM_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("PAPERFINDER_LLM_MODEL", "llama3.1:8b")
FRONTIER_MODEL = os.environ.get("PAPERFINDER_FRONTIER_MODEL", "claude-sonnet-4-6")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _post(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _local(prompt: str, system, max_tokens: int, timeout: int) -> str:
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    data = _post(LLM_URL.rstrip("/") + "/chat/completions",
                 {"model": LLM_MODEL, "messages": messages,
                  "stream": False, "temperature": 0.2},
                 {}, timeout)
    return data["choices"][0]["message"]["content"]


def _frontier(prompt: str, system, max_tokens: int, timeout: int) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set; cannot use the frontier model. "
                           "Either export it or run without --frontier to use the local model.")
    payload = {"model": FRONTIER_MODEL, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    if system:
        payload["system"] = system
    data = _post(ANTHROPIC_URL, payload,
                 {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout)
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def complete(prompt: str, system=None, frontier: bool = False,
             max_tokens: int = 1500, timeout: int = 180) -> str:
    """Return the model's text completion. frontier=False uses the local model."""
    return (_frontier if frontier else _local)(prompt, system, max_tokens, timeout)
