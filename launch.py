"""
Start the KPI API (FastAPI) first; once it is reachable, start the Vite UI.
Stop with Ctrl+C (or SIGTERM): child processes are terminated cleanly.

Run from the project root:
  python launch.py                  # main platform (frontend on :5173)
  python launch.py --insights-lab   # insights lab  (insights_lab on :5174)
  python launch.py --debug          # enable test-report store/load buttons
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(ROOT, "frontend")
INSIGHTS_LAB = os.path.join(ROOT, "insights_lab")

# No --reload: single uvicorn process so shutdown stays predictable.
API_CMD = [
    sys.executable,
    "-m",
    "uvicorn",
    "backend.app:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
    "--log-level",
    "info",
]


def _npm_run_dev() -> list[str] | str:
    if sys.platform == "win32":
        return "npm run dev"
    return ["npm", "run", "dev"]


def _wait_for_kpi_api(proc: subprocess.Popen, timeout_s: float = 90.0) -> None:
    """Block until GET /api/kpis returns 200 or the API process exits."""
    url = "http://127.0.0.1:8000/api/kpis"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code = proc.poll()
        if code is not None:
            print(f"KPI API exited with code {code}.", file=sys.stderr)
            sys.exit(code if code != 0 else 1)
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    print("KPI API did not become ready in time.", file=sys.stderr)
    sys.exit(1)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Launch Macro Brief platform.")
    p.add_argument(
        "--insights-lab",
        action="store_true",
        dest="insights_lab",
        help="Start the Insights Lab frontend (port 5174) instead of the main UI.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable test-report store/load buttons in the Country Brief UI.",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.debug:
        os.environ["MACROBRIEF_DEBUG"] = "1"
    os.chdir(ROOT)

    fe_dir = INSIGHTS_LAB if args.insights_lab else FRONTEND
    fe_label = "Insights Lab (port 5174)" if args.insights_lab else "Frontend (port 5173)"

    if not os.path.isdir(fe_dir):
        print(f"{fe_dir}/ not found — run this script from the project root.", file=sys.stderr)
        sys.exit(1)

    fe_shell = sys.platform == "win32"

    procs: list[subprocess.Popen] = []
    shutting_down = False

    def shutdown(_signum=None, _frame=None, exit_code: int = 0) -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        for p in procs:
            if p.poll() is None:
                p.terminate()
        deadline = time.time() + 12.0
        for p in procs:
            if p.poll() is not None:
                continue
            remaining = max(0, deadline - time.time())
            try:
                p.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                p.kill()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        sys.exit(exit_code)

    def handle_signal(signum, frame) -> None:
        shutdown(signum, frame, 0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        api_proc = subprocess.Popen(
            API_CMD,
            cwd=ROOT,
        )
        procs.append(api_proc)
        _wait_for_kpi_api(api_proc)
        print(f"Starting {fe_label}…")
        procs.append(
            subprocess.Popen(
                _npm_run_dev(),
                cwd=fe_dir,
                shell=fe_shell,
            )
        )
    except OSError as e:
        print(f"Failed to start process: {e}", file=sys.stderr)
        shutdown(exit_code=1)

    try:
        while True:
            for p in procs:
                code = p.poll()
                if code is not None:
                    if not shutting_down and code != 0:
                        print(f"Process exited with code {code}. Stopping others…", file=sys.stderr)
                    shutdown(exit_code=code if code is not None else 1)
            time.sleep(0.2)
    except KeyboardInterrupt:
        shutdown(exit_code=0)


if __name__ == "__main__":
    main()
