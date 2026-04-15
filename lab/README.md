# Lab — Experiment Scripts

This directory contains standalone experiment scripts that import from
`backend.services.*` and `backend.pipelines.*`. They are **not** part of the
production backend — they exist to test new pipeline steps, compare approaches,
and iterate on prompts without touching production code.

## Principles

1. **Experiments import production code, they never ARE production code.**
   If your experiment needs new logic, write that logic in `backend/services/`
   or `backend/pipelines/` (behind a flag if needed), then call it from here.

2. **Scripts are disposable.** When an experiment proves out, the useful code
   is already in production modules. Delete the lab script.

3. **Keep it simple.** Each script should do one thing and print results to
   stdout or save to `output/` (which is gitignored).

## Running

From the project root:

```bash
python -m lab.run_insights_pipeline --country SAU --kpi 3
python -m lab.run_country_brief_deep --country SAU
```

Or directly:

```bash
python lab/run_insights_pipeline.py --country SAU --kpi 3
```

## Structure

```
lab/
  README.md                      # this file
  run_insights_pipeline.py       # test the 7-step insights pipeline end-to-end
  run_country_brief_deep.py      # test country brief with deep_analysis=True
```
