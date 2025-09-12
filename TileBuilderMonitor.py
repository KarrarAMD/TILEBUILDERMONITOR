#!/usr/bin/env python3
import os
import sys
import time
import signal
import subprocess
import json
import argparse
from pathlib import Path

from TileBuilderMonitor_backend import Monitor 


def run_backend(backend_path: Path, workdir: Path) -> int:
    # Start backend as a subprocess and stream its output
    proc = subprocess.Popen(
        [sys.executable, str(backend_path)],
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    def _forward(sig, frame):
        try:
            proc.terminate()
        except Exception:
            pass
        sys.exit(1)

    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGQUIT", None)):
        if sig:
            try:
                signal.signal(sig, _forward)
            except Exception:
                pass

    try:
        # Print backend logs live
        assert proc.stdout is not None
        for line in proc.stdout:
            print(f"[backend] {line.rstrip()}")
    except Exception:
        pass
    finally:
        proc.wait()
    return proc.returncode


def wait_for_file(path: Path, timeout: float | None = None) -> bool:
    # Wait until file exists and has non-zero size; if timeout is None, wait indefinitely
    start = time.time()
    last_size = -1
    while True:
        if path.exists():
            size = path.stat().st_size
            if size > 0:
                # Final small settle check to avoid catching a mid-buffer write in exotic cases
                time.sleep(0.2)
                size2 = path.stat().st_size
                if size2 == size:
                    return True
                last_size = size2
        if timeout is not None and (time.time() - start) > timeout:
            return False
        time.sleep(0.2)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="TileBuilderMonitor",
        description="Run TileBuilder Monitor backend and frontend",
        add_help=True,
    )
    parser.add_argument("-u", "--user", dest="user", help="specify the user", default=None)
    parser.add_argument("-r", "--run", dest="run_dir", help="run area/dir", default=None)
    return parser.parse_args(argv)


def main():
    root = Path(__file__).resolve().parent
    backend = root / "TileBuilderMonitor_backend.py"
    frontend = root / "TileBuilderMonitor_frontend.py"
    out_dir = root / "tmp_TileBuilderMonitor" / Monitor.getUser()
    out_file = out_dir / "tmp.json"
    inputs_file = out_dir / "inputs.json"

    # Ensure fresh output directory
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_file.exists():
        try:
            out_file.unlink()
        except Exception:
            pass

    # Parse CLI args and write inputs.json so other tools can discover them
    args = parse_args(sys.argv[1:])
    print(f"{args=}")
    
    try:
        payload = {"user": args.user, "run_dir": args.run_dir}
        # Only include keys with values, or include both? Keep both keys for stability
        with inputs_file.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"[orchestrator] Failed to write inputs.json: {e}")

    print("[orchestrator] Starting backend...")
    rc = run_backend(backend, root)
    if rc != 0:
        print(f"[orchestrator] Backend exited with code {rc}. Aborting.")
        sys.exit(rc)

    print("[orchestrator] Backend finished. Verifying output file...")
    if not wait_for_file(out_file, timeout=10):
        print(f"[orchestrator] Output file not found or empty: {out_file}")
        sys.exit(1)

    print("[orchestrator] Launching frontend...")
    # Run frontend as a separate process so its Tk mainloop owns the process
    try:
        subprocess.run([sys.executable, str(frontend)], cwd=str(root), check=True)
    except subprocess.CalledProcessError as e:
        print(f"[orchestrator] Frontend exited with code {e.returncode}")
        sys.exit(e.returncode)


if __name__ == "__main__":
    main()