"""Backward-compatibility shim — logic lives in backend.services.signals."""
from backend.services.signals import extract_signals, filter_signals_with_questions  # noqa: F401
