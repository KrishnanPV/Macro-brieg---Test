"""Centralized configuration loaded from .env."""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# --- Oxford Economics / Knoema EAP ---
EAP_HOST = (os.getenv("EAP_HOST") or "").strip()
EAP_APP_ID = (os.getenv("EAP_APP_ID") or "").strip()
EAP_APP_SECRET = (os.getenv("EAP_APP_SECRET") or "").strip()
DATASET = "thrmeac"

# --- Newscatcher ---
NEWSCATCHER_API_KEY = (os.getenv("NEWSCATCHER_API_KEY") or "").strip()
NEWSCATCHER_URL = "https://v3-api.newscatcherapi.com/api/search"
NEWSCATCHER_TIMEOUT = 30

# --- OpenAI ---
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").strip()
OPENAI_MODEL = (os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL

# --- Perplexity (via OpenAI-compatible gateway) ---
PERPLEXITY_API_KEY = (os.getenv("PERPLEXITY_API_KEY") or "").strip()
_DEFAULT_PERPLEXITY_URL = "https://api.perplexity.ai"
PERPLEXITY_URL = (os.getenv("PERPLEXITY_URL") or "").strip() or _DEFAULT_PERPLEXITY_URL
PERPLEXITY_MODEL = (os.getenv("PERPLEXITY_MODEL") or "sonar").strip() or "sonar"

# --- Database ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/macrobrief.db")
