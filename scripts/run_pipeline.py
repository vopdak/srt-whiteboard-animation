import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from validate_projects import validate_project


ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"


def format_duration(seconds):
    minutes, seconds = divmod(round(seconds), 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


def validate(path):
    try:
        with path.open(encoding="utf-8") as file:
            project = json.load(file)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(exc) from exc

    errors = validate_project(project)
    if errors:
        raise RuntimeError("\n".join(errors))
    return project


def run_step(number, total, name, command=None, action=None):
    print(f"\n[START {number}/{total}] {name}", flush=True)
    started = time.monotonic()
    try:
        result = action() if action else subprocess.run(command, cwd=ROOT)
        if command and result.returncode != 0:
            raise RuntimeError(f"command exited with code {result.returncode}")
    except Exception as exc:
        print(f"[FAILED {number}/{total}] {name}: {exc}", flush=True)
        return None
    print(f"[OK {number}/{total}] {name} ({format_duration(time.monotonic() - started)})", flush=True)
    return result if command else result


def main():
    parser = argparse.ArgumentParser(
        description="Run validation, TTS, scene build, rendering, and final video composition"
    )
    parser.add_argument("project", nargs="?", type=Path, help="one input project JSON; omit to process all")
    args = parser.parse_args()

    project_path = args.project.resolve() if args.project else None
    files = [project_path] if project_path else sorted(INPUT_DIR.glob("*.json"))
    if not files:
        print("[FAILED] No project JSON files found.")
        return 1
    if any(not path.is_file() for path in files):
        missing = next(path for path in files if not path.is_file())
        print(f"[FAILED] Project file does not exist: {missing}")
        return 1

    started = time.monotonic()
    projects = []
    validation = run_step(
        1,
        5,
        "Validate project input",
        action=lambda: [validate(path) for path in files],
    )
    if validation is None:
        return 1
    projects = validation

    target_args = [str(project_path)] if project_path else []
    steps = [
        ("Generate narration and timeline", "generate_tts.py"),
        ("Build scene images and annotations", "build_scenes.py"),
        ("Render whiteboard scenes", "render_scenes.py"),
        ("Compose final video with narration", "compose_video.py"),
    ]
    for number, (name, script) in enumerate(steps, start=2):
        command = [sys.executable, "-u", str(ROOT / "scripts" / script), *target_args]
        if run_step(number, 5, name, command=command) is None:
            print("\nPipeline stopped. Fix the error above, then run the same command again.")
            return 1

    print(f"\n[DONE] Pipeline completed in {format_duration(time.monotonic() - started)}")
    for project in projects:
        print(f"[OUTPUT] output/{project['projectId']}/final.mp4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
