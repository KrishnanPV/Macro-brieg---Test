"""
Start the KPI API (FastAPI) first; once it is reachable, start the Vite UI.
Stop with Ctrl+C (or SIGTERM): child processes are terminated cleanly.

Run from the project root:
  python launch.py                  # main platform (frontend on :5173)
  python launch.py --debug          # enable test-report store/load buttons
  python launch.py --lab            # lab UI (frontend-lab on :5174)
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_MAIN = os.path.join(ROOT, "frontend")
FRONTEND_LAB = os.path.join(ROOT, "frontend-lab")

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


def _npm_run_dev(port: int) -> list[str] | str:
    if sys.platform == "win32":
        return f"npm run dev -- --port {port}"
    return ["npm", "run", "dev", "--", "--port", str(port)]


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


def _exit_if_port_busy(port: int) -> None:
    """Fail fast with a short message if another process already uses this port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        print("", file=sys.stderr)
        print(f"  PORT {port} IS ALREADY IN USE", file=sys.stderr)
        print("  -----------------------------", file=sys.stderr)
        print("  You probably still have Macro Brief running in another window.", file=sys.stderr)
        print("  Fix: go to that window and press Ctrl+C", file=sys.stderr)
        print("  Or run:  netstat -ano | findstr \":8000\"", file=sys.stderr)
        print("  Then:    taskkill /PID <number> /F   (use the LISTENING line)", file=sys.stderr)
        print("", file=sys.stderr)
        sys.exit(1)
    finally:
        s.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Launch Macro Brief platform.")
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable test-report store/load buttons in the Country Brief UI.",
    )
    p.add_argument(
        "--lab",
        action="store_true",
        help="Launch lab frontend (frontend-lab) on port 5174.",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.debug:
        os.environ["MACROBRIEF_DEBUG"] = "1"
    os.chdir(ROOT)

    frontend_dir = FRONTEND_LAB if args.lab else FRONTEND_MAIN
    frontend_port = 5174 if args.lab else 5173

    if not os.path.isdir(frontend_dir):
        print(f"{frontend_dir}/ not found — run this script from the project root.", file=sys.stderr)
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
        _exit_if_port_busy(8000)
        api_env = os.environ.copy()
        api_env["PYTHONUNBUFFERED"] = "1"
        api_proc = subprocess.Popen(
            API_CMD,
            cwd=ROOT,
            env=api_env,
        )
        procs.append(api_proc)
        _wait_for_kpi_api(api_proc)
        print()
        if args.lab:
            print("  >>> Lab mode enabled. Open the lab UI to inspect stage outputs.")
        else:
            print("  >>> Use this same window when you test Country Brief.")
            print("  >>> After you click Generate, look for:  Perplexity / news research")
        print()
        print(f"Starting Frontend (port {frontend_port})…")
        procs.append(
            subprocess.Popen(
                _npm_run_dev(frontend_port),
                cwd=frontend_dir,
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
