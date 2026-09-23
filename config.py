from __future__ import annotations

import os
from pathlib import Path

try:
    from crewai import LLM
except Exception:  # pragma: no cover - allows import-time environment checks without CrewAI
    LLM = None


def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def get_model_config() -> dict[str, str | None]:
    provider = (os.getenv("MODEL_PROVIDER") or os.getenv("LLM_PROVIDER") or "ollama").lower()
    if provider == "openai":
        base_model = os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        return {
            "provider": "openai",
            "model": base_model,
            "base_url": os.getenv("OPENAI_BASE_URL") or None,
            "api_key": os.getenv("OPENAI_API_KEY") or None,
        }

    base_model = os.getenv("MODEL_NAME") or os.getenv("OLLAMA_MODEL") or "llama3.2"
    if not base_model.startswith("ollama/"):
        base_model = f"ollama/{base_model}"
    return {
        "provider": "ollama",
        "model": base_model,
        "base_url": os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434",
        "api_key": None,
    }


def get_llm():
    if LLM is None:
        raise RuntimeError("crewai is not installed")

    config = get_model_config()
    kwargs: dict[str, str | None] = {"model": config["model"]}
    if config.get("base_url"):
        kwargs["base_url"] = config["base_url"]
    if config.get("api_key"):
        kwargs["api_key"] = config["api_key"]
    return LLM(**kwargs)
