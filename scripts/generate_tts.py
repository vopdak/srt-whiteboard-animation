import argparse
import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import wave
from pathlib import Path

from validate_projects import INPUT_DIR, ROOT, validate_project


SERVICE_URL = "http://127.0.0.1:8880/tts"
OUTPUT_DIR = ROOT / "output"


def request_audio(text, voice, speed):
    body = json.dumps({"text": text, "voice": voice, "speed": speed}).encode("utf-8")
    request = urllib.request.Request(
        SERVICE_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Kokoro service error: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "cannot connect to Kokoro service at http://127.0.0.1:8880; "
            "start it with: python services/kokoro/service.py"
        ) from exc


def read_wav(path):
    with wave.open(str(path), "rb") as wav:
        params = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
        frames = wav.readframes(wav.getnframes())
        return params, frames


def write_wav(path, params, frames):
    channels, sample_width, sample_rate = params
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)


def frames_to_ms(frame_count, sample_rate):
    return round(frame_count * 1000 / sample_rate)


def srt_timestamp(milliseconds):
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def write_subtitles(destination, project, timeline):
    timeline_scenes = {scene["id"]: scene for scene in timeline["scenes"]}
    entries = []
    index = 1
    for scene in project["scenes"]:
        timeline_segments = {
            segment["id"]: segment
            for segment in timeline_scenes[scene["id"]]["segments"]
        }
        for segment in scene["segments"]:
            timing = timeline_segments[segment["id"]]
            entries.extend([
                str(index),
                f"{srt_timestamp(timing['startMs'])} --> {srt_timestamp(timing['endMs'])}",
                segment["ttsText"].strip(),
                "",
            ])
            index += 1
    (destination / "subtitles.srt").write_text(
        "\n".join(entries),
        encoding="utf-8",
    )


def require_safe_id(value, label):
    if value in (".", "..") or Path(value).name != value or "/" in value or "\\" in value:
        raise RuntimeError(f'{label} "{value}" cannot be used as a file or directory name')


def generate_project(project, destination):
    voice = project["voice"]["id"]
    speed = project["voice"]["speed"]
    padding_ms = project["timing"]["sceneEndPaddingMs"]
    audio_dir = destination / "audio"
    audio_dir.mkdir(parents=True)

    timeline = {"projectId": project["projectId"], "durationMs": 0, "scenes": []}
    narration_frames = bytearray()
    expected_params = None
    project_frame = 0

    for scene in project["scenes"]:
        scene_id = scene["id"]
        require_safe_id(scene_id, "scene id")
        scene_dir = audio_dir / scene_id
        scene_dir.mkdir()
        scene_start_frame = project_frame
        scene_frames = bytearray()
        segment_entries = []

        for segment in scene["segments"]:
            segment_id = segment["id"]
            require_safe_id(segment_id, "segment id")
            text = segment["ttsText"]
            if not text.strip():
                raise RuntimeError(f'{scene_id}/{segment_id}: ttsText is empty')
            wav_path = scene_dir / f"{segment_id}.wav"
            try:
                wav_path.write_bytes(request_audio(text, voice, speed))
                params, frames = read_wav(wav_path)
            except Exception as exc:
                raise RuntimeError(f"{scene_id}/{segment_id}: TTS failed: {exc}") from exc
            if not frames:
                raise RuntimeError(f"{scene_id}/{segment_id}: Kokoro created an empty WAV")
            if expected_params is None:
                expected_params = params
            elif params != expected_params:
                raise RuntimeError(f"{scene_id}/{segment_id}: WAV format does not match previous segments")

            channels, sample_width, sample_rate = params
            frame_count = len(frames) // (channels * sample_width)
            segment_start = project_frame
            project_frame += frame_count
            scene_frames.extend(frames)
            segment_start_ms = frames_to_ms(segment_start, sample_rate)
            segment_end_ms = frames_to_ms(project_frame, sample_rate)
            segment_entries.append({
                "id": segment_id,
                "startMs": segment_start_ms,
                "endMs": segment_end_ms,
                "durationMs": segment_end_ms - segment_start_ms,
                "elementIds": segment["elementIds"],
            })

        if expected_params is None:
            raise RuntimeError(f"{scene_id}: scene contains no audio segments")
        channels, sample_width, sample_rate = expected_params
        padding_frames = round(padding_ms * sample_rate / 1000)
        silence = bytes(padding_frames * channels * sample_width)
        scene_frames.extend(silence)
        project_frame += padding_frames
        write_wav(audio_dir / f"{scene_id}.wav", expected_params, scene_frames)
        narration_frames.extend(scene_frames)
        scene_start_ms = frames_to_ms(scene_start_frame, sample_rate)
        scene_end_ms = frames_to_ms(project_frame, sample_rate)
        timeline["scenes"].append({
            "id": scene_id,
            "startMs": scene_start_ms,
            "endMs": scene_end_ms,
            "durationMs": scene_end_ms - scene_start_ms,
            "segments": segment_entries,
        })

    write_wav(audio_dir / "narration.wav", expected_params, narration_frames)
    timeline["durationMs"] = frames_to_ms(project_frame, expected_params[2])
    (destination / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_subtitles(destination, project, timeline)


def process_file(path):
    try:
        project = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"[FAILED] {path.name}: cannot read JSON: {exc}")
        return False

    errors = validate_project(project)
    if errors:
        print(f"[SKIPPED] {path.name}: validation failed")
        for error in errors:
            print(error)
        return False

    try:
        require_safe_id(project["projectId"], "projectId")
    except RuntimeError as exc:
        print(f"[FAILED] {path.name}: {exc}")
        return False
    final_dir = OUTPUT_DIR / project["projectId"]
    OUTPUT_DIR.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{project['projectId']}-", dir=OUTPUT_DIR) as temp:
        temp_dir = Path(temp)
        try:
            generate_project(project, temp_dir)
        except Exception as exc:
            print(f"[FAILED] {path.name}: {exc}")
            return False
        if final_dir.exists():
            shutil.rmtree(final_dir)
        temp_dir.replace(final_dir)
    print(f"[GENERATED] {path.name}: {final_dir.relative_to(ROOT)}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Generate Kokoro narration and timeline")
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
