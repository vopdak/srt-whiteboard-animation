import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
AUDIO_SAMPLE_RATE = 48000


class FFmpegError(RuntimeError):
    pass


def safe_id(value, label):
    if value in (".", "..") or Path(value).name != value or "/" in value or "\\" in value:
        raise RuntimeError(f'{label} "{value}" cannot be used as a file name')


def command_text(command):
    return subprocess.list2cmdline([str(part) for part in command])


def run_ffmpeg(command, project_id, scene_id):
    result = subprocess.run(
        [str(part) for part in command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise FFmpegError(
            f"Project ID: {project_id}\n"
            f"Scene ID: {scene_id}\n"
            f"Command: {command_text(command)}\n"
            f"Exit code: {result.returncode}\n"
            f"stderr: {result.stderr.strip() or 'FFmpeg returned no stderr'}"
        )


def compose_scene(ffmpeg, project, scene, scene_timeline, project_dir):
    project_id = project["projectId"]
    scene_id = scene["id"]
    scenes_dir = project_dir / "scenes"
    video = scenes_dir / f"{scene_id}-whiteboard.mp4"
    audio = project_dir / "audio" / f"{scene_id}.wav"
    output = scenes_dir / f"{scene_id}-with-audio.mp4"
    temporary = scenes_dir / f".{scene_id}-with-audio.tmp.mp4"
    for path, label in ((video, "whiteboard video"), (audio, "scene audio")):
        if not path.is_file():
            raise RuntimeError(f"{project_id}/{scene_id}: missing {label}: {path}")

    duration_ms = scene_timeline.get("durationMs")
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms <= 0:
        raise RuntimeError(f"{project_id}/{scene_id}: invalid timeline durationMs")
    try:
        with wave.open(str(audio), "rb") as wav:
            audio_duration = wav.getnframes() / wav.getframerate()
    except (OSError, wave.Error, ZeroDivisionError) as exc:
        raise RuntimeError(f"{project_id}/{scene_id}: cannot read scene WAV: {exc}") from exc
    effective_duration = max(duration_ms / 1000, audio_duration)
    duration = f"{effective_duration:.6f}"
    width = project["resolution"]["width"]
    height = project["resolution"]["height"]
    fps = project["fps"]
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={fps},tpad=stop_mode=clone:stop_duration={duration},"
        f"trim=duration={duration},setpts=PTS-STARTPTS"
    )
    audio_filter = (
        f"aresample={AUDIO_SAMPLE_RATE}:async=1:first_pts=0,"
        f"apad=whole_dur={duration},atrim=duration={duration},asetpts=PTS-STARTPTS"
    )
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", video, "-i", audio,
        "-filter_complex", f"[0:v]{video_filter}[v];[1:a]{audio_filter}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE),
        "-movflags", "+faststart", temporary,
    ]
    temporary.unlink(missing_ok=True)
    try:
        run_ffmpeg(command, project_id, scene_id)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise FFmpegError(
                f"Project ID: {project_id}\nScene ID: {scene_id}\n"
                f"Command: {command_text(command)}\nExit code: 0\n"
                "stderr: FFmpeg completed without creating a scene video"
            )
        output.unlink(missing_ok=True)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"[MUXED] {project_id}/{scene_id}: {output.relative_to(ROOT)}")
    return output


def concat_scenes(ffmpeg, project, scene_videos, project_dir):
    project_id = project["projectId"]
    final = project_dir / "final.mp4"
    temporary = project_dir / ".final.tmp.mp4"
    width = project["resolution"]["width"]
    height = project["resolution"]["height"]
    fps = project["fps"]

    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", prefix=".concat-", dir=project_dir,
        delete=False, encoding="utf-8"
    ) as file:
        for video in scene_videos:
            escaped = video.resolve().as_posix().replace("'", "'\\''")
            file.write(f"file '{escaped}'\n")
        concat_list = Path(file.name)

    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", concat_list,
        "-vf", f"scale={width}:{height},fps={fps}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_SAMPLE_RATE),
        "-movflags", "+faststart", temporary,
    ]
    temporary.unlink(missing_ok=True)
    try:
        run_ffmpeg(command, project_id, "<concat>")
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise FFmpegError(
                f"Project ID: {project_id}\nScene ID: <concat>\n"
                f"Command: {command_text(command)}\nExit code: 0\n"
                "stderr: FFmpeg completed without creating final video"
            )
        final.unlink(missing_ok=True)
        temporary.replace(final)
    finally:
        temporary.unlink(missing_ok=True)
        concat_list.unlink(missing_ok=True)
    print(f"[COMPOSED] {project_id}: {final.relative_to(ROOT)}")
    return final


def process_file(path, ffmpeg):
    try:
        project = json.loads(path.read_text(encoding="utf-8"))
        project_id = project["projectId"]
        safe_id(project_id, "projectId")
        project_dir = OUTPUT_DIR / project_id
        timeline_path = project_dir / "timeline.json"
        if not timeline_path.is_file():
            raise RuntimeError(f"{project_id}: missing timeline: {timeline_path}")
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        if timeline.get("projectId") != project_id:
            raise RuntimeError(f"{project_id}: timeline projectId does not match")
        timeline_scenes = {scene["id"]: scene for scene in timeline.get("scenes", [])}
        scene_videos = []
        for scene in project["scenes"]:
            scene_id = scene["id"]
            safe_id(scene_id, "scene id")
            scene_timeline = timeline_scenes.get(scene_id)
            if scene_timeline is None:
                raise RuntimeError(f"{project_id}/{scene_id}: missing scene timeline")
            scene_videos.append(compose_scene(ffmpeg, project, scene, scene_timeline, project_dir))
        if not scene_videos:
            raise RuntimeError(f"{project_id}: project has no scenes")
        concat_scenes(ffmpeg, project, scene_videos, project_dir)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, RuntimeError) as exc:
        print(f"[FAILED] {path.name}: {exc}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Mux narration and compose the final project video")
    parser.add_argument("project", nargs="?", type=Path, help="one input project JSON")
    args = parser.parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("FFmpeg is required but was not found in PATH. Install FFmpeg and run: ffmpeg -version")
        return 1
    files = [args.project] if args.project else sorted(INPUT_DIR.glob("*.json"))
    if not files:
        print("No project JSON files found.")
        return 1
    succeeded = True
    for path in files:
        if not process_file(path.resolve(), ffmpeg):
            succeeded = False
    return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
