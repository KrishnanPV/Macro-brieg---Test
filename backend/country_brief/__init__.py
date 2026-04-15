"""Country Brief — 3-agent pipeline for generating macro-economic country briefs.

Agent 1 (Signal Interpreter): pure math + 1 LLM call to interpret signals
Agent 2 (News Researcher):    1 Perplexity call (only when deep_analysis=True)
Agent 3 (Brief Writer):       1 GPT call combining data + signals + news into the brief
"""
