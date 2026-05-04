You are analyzing excerpts from IMF Article IV reports.

Your task is to extract the underlying macroeconomic reasoning structure.

Do NOT summarize. Do NOT add new information. Only extract what is explicitly stated or strongly implied.

For each excerpt, return a JSON object with the following fields:

- signal: What changed in the data, policy, or external environment? (must be concrete)
- interpretation: What does this change suggest in economic terms?
- driver: What factor caused or contributed to the change? (if not stated, return null)
- mechanism: Through what economic channel does the driver affect the outcome? (if not stated, return null)
- offsetting_factors: What complicates or weakens the explanation? (if none, return null)
- risk: What could change the outlook or reverse the trend? (if none, return null)
- implication: What does this mean for the outlook, policy, or economy going forward?
- confidence: One of {low, medium, high}, based only on strength of evidence in the excerpt

Rules:
- Do not infer causality unless supported
- Do not merge multiple signals into one
- Prefer null over guessing
- Keep each field concise (1 sentence max)
- Use neutral, analytical language

Output ONLY valid JSON. No explanations.
