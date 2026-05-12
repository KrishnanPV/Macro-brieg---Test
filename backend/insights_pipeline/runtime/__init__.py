"""Runtime helpers shared across insights consumers."""

from .prompt_loader import PROMPTS_DIR, load_prompt_manifest, load_prompt_text

__all__ = ["PROMPTS_DIR", "load_prompt_manifest", "load_prompt_text"]

