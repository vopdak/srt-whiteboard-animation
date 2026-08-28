import argparse
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

from validate_projects import INPUT_DIR, ROOT, validate_project

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow is required. Install it with: python -m pip install Pillow", file=sys.stderr)
    raise SystemExit(1)


BACKGROUND = "#F5EBD7"
OUTPUT_DIR = ROOT / "output"
POSITIONS = {
    "top-left": (0, 0), "top-center": (1, 0), "top-right": (2, 0),
    "left": (0, 1), "center": (1, 1), "right": (2, 1),
    "bottom-left": (0, 2), "bottom-center": (1, 2), "bottom-right": (2, 2),
}
SIZE_FACTORS = {"small": 0.52, "medium": 0.72, "large": 0.92}
IMAGE_SCALE = 2


def safe_id(value, label):
    if value in (".", "..") or Path(value).name != value or "/" in value or "\\" in value:
        raise RuntimeError(f'{label} "{value}" cannot be used as a file name')


def load_font(size):
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def fit_image(asset_path, max_width, max_height):
    image = Image.open(asset_path).convert("RGBA")
    visible = image.getchannel("A").getbbox()
    if visible is None:
        raise RuntimeError(f'asset has no visible pixels: "{asset_path}"')
    image = image.crop(visible)
    scale = min(max_width / image.width, max_height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def wrap_text(text, font, max_width):
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render_text(text, size_name, max_width, max_height, canvas_height):
    font_ratio = {"small": 0.032, "medium": 0.045, "large": 0.06}[size_name]
    font_size = max(18, round(canvas_height * font_ratio))
    while font_size >= 12:
        font = load_font(font_size)
        lines = wrap_text(text, font, max_width)
        spacing = max(4, font_size // 5)
        sample = "\n".join(lines)
        box = ImageDraw.Draw(Image.new("L", (1, 1))).multiline_textbbox(
            (0, 0), sample, font=font, spacing=spacing, align="center", stroke_width=1
        )
        width, height = box[2] - box[0], box[3] - box[1]
        if width <= max_width and height <= max_height:
            # Some Pillow/font combinations return floating-point text bounds.
            # Image dimensions must always be integers and must not round down.
            image_size = (
                max(1, math.ceil(width + 8)),
                max(1, math.ceil(height + 8)),
            )
            image = Image.new("RGBA", image_size, (0, 0, 0, 0))
            ImageDraw.Draw(image).multiline_text(
                (image.width // 2, 4 - box[1]), sample, font=font, fill="#333333",
                spacing=spacing, align="center", anchor="ma", stroke_width=1, stroke_fill="#333333"
            )
            visible = image.getchannel("A").getbbox()
            return image.crop(visible)
        font_size -= 2
    raise RuntimeError("text does not fit its layout slot")


def layout_scene(project, scene, canvas):
    width, height = canvas.size
    margin_x = round(width * 0.04)
    margin_top = round(height * 0.04)
    subtitle_top = round(height * 0.85)
    gap = max(12, round(min(width, height) * 0.018))
    usable_width = width - 2 * margin_x
    usable_height = subtitle_top - margin_top
    cell_width = usable_width / 3
    cell_height = usable_height / 3

    buckets = {position: [] for position in POSITIONS}
    for element in scene["elements"]:
        position = element["position"]
        size = element["size"]
        if position not in POSITIONS:
            raise RuntimeError(f'{scene["id"]}/{element["id"]}: unsupported position "{position}"')
        if size not in SIZE_FACTORS:
            raise RuntimeError(f'{scene["id"]}/{element["id"]}: unsupported size "{size}"')
        buckets[position].append(element)

    regions = {}
    for position, elements in buckets.items():
        elements.sort(key=lambda item: item["sequence"])
        column, row = POSITIONS[position]
        count = len(elements)
        if not count:
            continue
        slot_height = cell_height / count
        for index, element in enumerate(elements):
            factor = SIZE_FACTORS[element["size"]]
            max_width = max(1, round((cell_width - 2 * gap) * factor))
            max_height = max(1, round((slot_height - gap) * factor))
            if element["type"] == "image":
                asset_path = (ROOT / element["asset"]).resolve()
                if not asset_path.is_file():
                    raise RuntimeError(f'{scene["id"]}/{element["id"]}: missing asset "{element["asset"]}"')
                visual = fit_image(
                    asset_path,
                    max_width * IMAGE_SCALE,
                    max_height * IMAGE_SCALE,
                )
            else:
                visual = render_text(
                    element["content"], element["size"], max_width, max_height, height
                )

            center_x = margin_x + (column + 0.5) * cell_width
            center_y = margin_top + row * cell_height + (index + 0.5) * slot_height
            x = max(0, min(width - visual.width, round(center_x - visual.width / 2)))
            y = max(0, min(subtitle_top - visual.height, round(center_y - visual.height / 2)))
            canvas.alpha_composite(visual, (x, y))
            regions[element["id"]] = {
                "x": x, "y": y, "width": visual.width, "height": visual.height
            }
    return regions


def element_timings(scene, scene_timeline, completed_hold_ms):
    scene_start = scene_timeline["startMs"]
    scene_duration = scene_timeline["durationMs"]
    deadline = scene_duration - completed_hold_ms
    if deadline < 0:
        raise RuntimeError(f'{scene["id"]}: completedSceneHoldMs exceeds scene duration')

    timeline_segments = {segment["id"]: segment for segment in scene_timeline["segments"]}
    elements = {element["id"]: element for element in scene["elements"]}
    timings = {}
    for segment in scene["segments"]:
        segment_timeline = timeline_segments.get(segment["id"])
        if segment_timeline is None:
            raise RuntimeError(f'{scene["id"]}/{segment["id"]}: missing segment timeline')
        pending = []
        pending_ids = set()
        for element_id in segment["elementIds"]:
            if element_id not in timings and element_id not in pending_ids:
                pending.append(elements[element_id])
                pending_ids.add(element_id)
        pending.sort(key=lambda item: item["sequence"])
        if not pending:
            continue
        start = segment_timeline["startMs"] - scene_start
        end = min(segment_timeline["endMs"] - scene_start, deadline)
        if end <= start:
            raise RuntimeError(
                f'{scene["id"]}/{segment["id"]}: no drawing time remains before completed scene hold'
            )
        for index, element in enumerate(pending):
            element_start = round(start + (end - start) * index / len(pending))
            element_end = round(start + (end - start) * (index + 1) / len(pending))
            timings[element["id"]] = (element_start, element_end)

    missing = [element_id for element_id in elements if element_id not in timings]
    if missing:
        raise RuntimeError(f'{scene["id"]}: elements not referenced by any segment: {", ".join(missing)}')
    return timings


def build_project(project, timeline, destination):
    if timeline.get("projectId") != project["projectId"]:
        raise RuntimeError("timeline projectId does not match project JSON")
    width = project["resolution"]["width"]
    height = project["resolution"]["height"]
    hold_ms = project["timing"]["completedSceneHoldMs"]
    timeline_scenes = {scene["id"]: scene for scene in timeline.get("scenes", [])}

    for scene in project["scenes"]:
        scene_id = scene["id"]
        safe_id(scene_id, "scene id")
        scene_timeline = timeline_scenes.get(scene_id)
        if scene_timeline is None:
            raise RuntimeError(f"{scene_id}: missing scene timeline")
        canvas = Image.new("RGBA", (width, height), BACKGROUND)
        regions = layout_scene(project, scene, canvas)
        timings = element_timings(scene, scene_timeline, hold_ms)

        annotations = []
        segment_text = {}
        for segment in scene["segments"]:
            for element_id in segment["elementIds"]:
                segment_text.setdefault(element_id, segment["ttsText"])
        for element in sorted(scene["elements"], key=lambda item: item["sequence"]):
            start_ms, end_ms = timings[element["id"]]
            region = regions[element["id"]]
            center_x = region["x"] + region["width"] // 2
            annotations.append({
                "id": element["id"],
                "label": element.get("content", element["id"]),
                "sequence": element["sequence"],
                "narrativeRole": element["type"],
                "subtitle": segment_text[element["id"]],
                "type": element["type"],
                "startMs": start_ms,
                "endMs": end_ms,
                "durationMs": end_ms - start_ms,
                "region": region,
                "reveal": {
                    "direction": "top_to_bottom",
                    "startMs": start_ms,
                    "durationMs": end_ms - start_ms,
                    "maskPaddingPx": 0,
                    "protectedRegions": [],
                },
                "handPath": {
                    "start": [center_x, region["y"]],
                    "end": [center_x, region["y"] + region["height"]],
                    "easing": "easeInOut",
                },
            })

        annotation = {
            "sceneId": scene_id,
            "canvas": {"width": width, "height": height},
            "storyBasis": " ".join(segment["ttsText"] for segment in scene["segments"]),
            "startMs": scene_timeline["startMs"],
            "endMs": scene_timeline["endMs"],
            "sceneDurationMs": scene_timeline["durationMs"],
            "completedSceneHoldMs": hold_ms,
            "elements": annotations,
        }
        canvas.convert("RGB").save(destination / f"{scene_id}.png")
        (destination / f"{scene_id}.annotation.json").write_text(
            json.dumps(annotation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def check_audio(project, project_dir):
    audio_dir = project_dir / "audio"
    if not (audio_dir / "narration.wav").is_file():
        raise RuntimeError("missing audio/narration.wav")
    for scene in project["scenes"]:
        if not (audio_dir / f'{scene["id"]}.wav').is_file():
            raise RuntimeError(f'missing audio/{scene["id"]}.wav')
        for segment in scene["segments"]:
            path = audio_dir / scene["id"] / f'{segment["id"]}.wav'
            if not path.is_file():
                raise RuntimeError(f'missing audio/{scene["id"]}/{segment["id"]}.wav')


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
        safe_id(project["projectId"], "projectId")
        project_dir = OUTPUT_DIR / project["projectId"]
        timeline_path = project_dir / "timeline.json"
        if not timeline_path.is_file():
            raise RuntimeError("missing timeline.json")
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        check_audio(project, project_dir)
        with tempfile.TemporaryDirectory(prefix=".scenes-", dir=project_dir) as temp:
            temp_dir = Path(temp)
            build_project(project, timeline, temp_dir)
            scenes_dir = project_dir / "scenes"
            if scenes_dir.exists():
                shutil.rmtree(scenes_dir)
            temp_dir.replace(scenes_dir)
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(f"[FAILED] {path.name}: {exc}")
        return False
    print(f"[BUILT] {path.name}: output/{project['projectId']}/scenes")
    return True


def main():
    parser = argparse.ArgumentParser(description="Build deterministic scene PNGs and annotations")
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
