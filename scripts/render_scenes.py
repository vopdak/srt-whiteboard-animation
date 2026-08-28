import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
RENDERER = ROOT / "scripts" / "render_stream_whiteboard.py"
HAND_IMAGE = ROOT / "assets" / "drawing-hand.png"


def safe_id(value, label):
    if value in (".", "..") or Path(value).name != value or "/" in value or "\\" in value:
        raise RuntimeError(f'{label} "{value}" cannot be used as a file name')


def command_text(command):
    return subprocess.list2cmdline([str(part) for part in command])


def render_scene(project_id, scene_id, fps, duration_ms, scenes_dir):
    image = scenes_dir / f"{scene_id}.png"
    annotation = scenes_dir / f"{scene_id}.annotation.json"
    output = scenes_dir / f"{scene_id}-whiteboard.mp4"
    for path, label in (
        (image, "scene PNG"),
        (annotation, "annotation"),
        (HAND_IMAGE, "drawing hand image"),
    ):
        if not path.is_file():
            raise RuntimeError(f"{project_id}/{scene_id}: missing {label}: {path}")

    try:
        annotation_data = json.loads(annotation.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{project_id}/{scene_id}: cannot read annotation: {exc}") from exc
    if annotation_data.get("sceneId") != scene_id:
        raise RuntimeError(f"{project_id}/{scene_id}: annotation sceneId does not match")
    if annotation_data.get("sceneDurationMs") != duration_ms:
        raise RuntimeError(
            f"{project_id}/{scene_id}: annotation duration does not match timeline "
            f"({annotation_data.get('sceneDurationMs')} != {duration_ms})"
        )
    if not annotation_data.get("elements"):
        raise RuntimeError(f"{project_id}/{scene_id}: annotation has no elements")

    newest_input = max(image.stat().st_mtime, annotation.stat().st_mtime)
    if output.is_file() and output.stat().st_mtime >= newest_input:
        print(f"[SKIPPED] {project_id}/{scene_id}: video is up to date")
        return

    temporary = scenes_dir / f".{scene_id}-whiteboard.tmp.mp4"
    temporary_raw = temporary.with_name(temporary.stem + "_raw.mp4")
    command = [
        sys.executable,
        RENDERER,
        image,
        annotation,
        temporary,
        HAND_IMAGE,
        "--fps", str(fps),
        "--total-ms", str(duration_ms),
        "--ink-path", "grid",
        "--color-fill", "contour-wipe",
    ]
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [str(part) for part in command],
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        temporary_raw.unlink(missing_ok=True)
        details = result.stderr.strip() or result.stdout.strip() or "renderer returned no error output"
        raise RuntimeError(
            f"Project ID: {project_id}\n"
            f"Scene ID: {scene_id}\n"
            f"Command: {command_text(command)}\n"
            f"Exit code: {result.returncode}\n"
            f"Error: {details}"
        )

    rendered = temporary if temporary.is_file() else temporary_raw
    if not rendered.is_file() or rendered.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        temporary_raw.unlink(missing_ok=True)
        raise RuntimeError(
            f"Project ID: {project_id}\n"
            f"Scene ID: {scene_id}\n"
            f"Command: {command_text(command)}\n"
            f"Exit code: {result.returncode}\n"
            "Error: renderer completed without creating a video"
        )
    output.unlink(missing_ok=True)
    rendered.replace(output)
    temporary.unlink(missing_ok=True)
    temporary_raw.unlink(missing_ok=True)
    print(f"[RENDERED] {project_id}/{scene_id}: {output.relative_to(ROOT)}")


def process_file(path):
    try:
        project = json.loads(path.read_text(encoding="utf-8"))
        project_id = project["projectId"]
        fps = project["fps"]
        scenes = project["scenes"]
        safe_id(project_id, "projectId")
        if isinstance(fps, bool) or not isinstance(fps, int) or fps <= 0:
            raise RuntimeError("fps must be a positive integer")
        project_dir = OUTPUT_DIR / project_id
        timeline_path = project_dir / "timeline.json"
        if not timeline_path.is_file():
            raise RuntimeError(f"{project_id}: missing timeline: {timeline_path}")
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        if timeline.get("projectId") != project_id:
            raise RuntimeError(f"{project_id}: timeline projectId does not match")
        timeline_scenes = {scene["id"]: scene for scene in timeline.get("scenes", [])}
        scenes_dir = project_dir / "scenes"

        for scene in scenes:
            scene_id = scene["id"]
            safe_id(scene_id, "scene id")
            scene_timeline = timeline_scenes.get(scene_id)
            if scene_timeline is None:
                raise RuntimeError(f"{project_id}/{scene_id}: missing scene timeline")
            duration_ms = scene_timeline.get("durationMs")
            if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms <= 0:
                raise RuntimeError(f"{project_id}/{scene_id}: invalid timeline durationMs")
            render_scene(project_id, scene_id, fps, duration_ms, scenes_dir)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, RuntimeError) as exc:
        print(f"[FAILED] {path.name}: {exc}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Render whiteboard animation for project scenes")
    parser.add_argument("project", nargs="?", type=Path, help="one input project JSON")
    args = parser.parse_args()
    files = [args.project] if args.project else sorted(INPUT_DIR.glob("*.json"))
    if not files:
        print("No project JSON files found.")
        return 1
    succeeded = True
    for path in files:
        if not process_file(path.resolve()):
            succeeded = False
    return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
