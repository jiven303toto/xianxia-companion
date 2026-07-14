import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent


def _stop_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    process.kill()


def _stop_processes(processes: list[tuple[str, subprocess.Popen]]) -> None:
    if os.name == "nt":
        for _, process in processes:
            _stop_process_tree(process)
        for _, process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        return

    for _, process in processes:
        if process.poll() is None:
            process.terminate()

    deadline = time.monotonic() + 10
    for _, process in processes:
        if process.poll() is not None:
            continue
        timeout = max(0.1, deadline - time.monotonic())
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop_process_tree(process)


def run_all() -> int:
    processes: list[tuple[str, subprocess.Popen]] = []
    targets = (
        ("web", ROOT_DIR / "run_web.py"),
        ("telegram", ROOT_DIR / "run_telegram.py"),
    )
    try:
        for name, script in targets:
            process = subprocess.Popen([sys.executable, str(script)], cwd=ROOT_DIR)
            processes.append((name, process))
            print(f"Started {name}: pid={process.pid}")

        while True:
            for name, process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    print(f"{name} exited with code {exit_code}; stopping all services.")
                    return exit_code
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping all services...")
        return 130
    finally:
        _stop_processes(processes)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local launcher")
    parser.add_argument(
        "target",
        choices=("web", "telegram", "all"),
        nargs="?",
        default="web",
        help="target to start, default: web",
    )
    args = parser.parse_args()

    if args.target == "all":
        raise SystemExit(run_all())

    if args.target == "telegram":
        from run_telegram import run_telegram_runtime

        run_telegram_runtime()
        return

    from run_web import main as run_web_main

    run_web_main()


if __name__ == "__main__":
    main()
