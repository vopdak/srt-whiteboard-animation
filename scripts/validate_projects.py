import json
from pathlib import Path, PurePath


ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
ASSETS_DIR = (ROOT / "assets").resolve()


def validate_project(data):
    errors = []

    def error(path, message):
        errors.append(f"{path}: {message}")

    def require_object(value, path):
        if not isinstance(value, dict):
            error(path, "must be an object")
            return False
        return True

    def require_list(value, path):
        if not isinstance(value, list):
            error(path, "must be an array")
            return False
        return True

    def require_string(obj, key, path):
        value = obj.get(key)
        field_path = f"{path}.{key}"
        if not isinstance(value, str) or not value.strip():
            error(field_path, "must be a non-empty string")
            return None
        return value

    def require_number(obj, key, path, *, integer=False, positive=False):
        value = obj.get(key)
        field_path = f"{path}.{key}"
        expected = int if integer else (int, float)
        if isinstance(value, bool) or not isinstance(value, expected):
            error(field_path, "must be an integer" if integer else "must be a number")
            return
        if positive and value <= 0:
            error(field_path, "must be greater than 0")

    if not require_object(data, "$"):
        return errors

    require_string(data, "projectId", "$")
    require_string(data, "title", "$")

    resolution = data.get("resolution")
    if require_object(resolution, "$.resolution"):
        require_number(resolution, "width", "$.resolution", integer=True, positive=True)
        require_number(resolution, "height", "$.resolution", integer=True, positive=True)
    require_number(data, "fps", "$", integer=True, positive=True)

    voice = data.get("voice")
    if require_object(voice, "$.voice"):
        require_string(voice, "id", "$.voice")
        require_number(voice, "speed", "$.voice", positive=True)

    timing = data.get("timing")
    if require_object(timing, "$.timing"):
        for key in ("sceneEndPaddingMs", "completedSceneHoldMs", "minimumElementDurationMs"):
            require_number(timing, key, "$.timing", integer=True)
            value = timing.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value < 0:
                error(f"$.timing.{key}", "must be 0 or greater")

    scenes = data.get("scenes")
    if not require_list(scenes, "$.scenes"):
        return errors
    if not scenes:
        error("$.scenes", "must contain at least one scene")

    scene_ids = set()
    for scene_index, scene in enumerate(scenes):
        scene_path = f"$.scenes[{scene_index}]"
        if not require_object(scene, scene_path):
            continue
        scene_id = require_string(scene, "id", scene_path)
        if scene_id in scene_ids:
            error(f"{scene_path}.id", f'duplicate scene id "{scene_id}"')
        elif scene_id:
            scene_ids.add(scene_id)

        elements = scene.get("elements")
        element_ids = set()
        if require_list(elements, f"{scene_path}.elements"):
            for element_index, element in enumerate(elements):
                element_path = f"{scene_path}.elements[{element_index}]"
                if not require_object(element, element_path):
                    continue
                element_id = require_string(element, "id", element_path)
                if element_id in element_ids:
                    error(f"{element_path}.id", f'duplicate element id "{element_id}" in this scene')
                elif element_id:
                    element_ids.add(element_id)

                element_type = require_string(element, "type", element_path)
                if element_type not in (None, "text", "image"):
                    error(f"{element_path}.type", 'must be "text" or "image"')
                if element_type == "text":
                    require_string(element, "content", element_path)
                if element_type == "image":
                    asset = require_string(element, "asset", element_path)
                    if asset:
                        normalized = asset.replace("\\", "/")
                        parts = PurePath(normalized).parts
                        if Path(asset).is_absolute() or normalized.startswith("/"):
                            error(f"{element_path}.asset", "absolute paths are not allowed")
                        elif ".." in parts:
                            error(f"{element_path}.asset", 'must not contain ".."')
                        elif not parts or parts[0] != "assets":
                            error(f"{element_path}.asset", 'must be inside the "assets/" directory')
                        else:
                            asset_path = (ROOT / Path(*parts)).resolve()
                            try:
                                asset_path.relative_to(ASSETS_DIR)
                            except ValueError:
                                error(f"{element_path}.asset", 'must be inside the "assets/" directory')
                            else:
                                if not asset_path.is_file():
                                    error(f"{element_path}.asset", f'file does not exist: "{asset}"')

                require_string(element, "position", element_path)
                require_string(element, "size", element_path)
                require_number(element, "sequence", element_path, integer=True, positive=True)

        segments = scene.get("segments")
        if require_list(segments, f"{scene_path}.segments"):
            segment_ids = set()
            for segment_index, segment in enumerate(segments):
                segment_path = f"{scene_path}.segments[{segment_index}]"
                if not require_object(segment, segment_path):
                    continue
                segment_id = require_string(segment, "id", segment_path)
                if segment_id in segment_ids:
                    error(f"{segment_path}.id", f'duplicate segment id "{segment_id}" in this scene')
                elif segment_id:
                    segment_ids.add(segment_id)
                require_string(segment, "ttsText", segment_path)
                references = segment.get("elementIds")
                if require_list(references, f"{segment_path}.elementIds"):
                    for reference_index, reference in enumerate(references):
                        reference_path = f"{segment_path}.elementIds[{reference_index}]"
                        if not isinstance(reference, str) or not reference.strip():
                            error(reference_path, "must be a non-empty string")
                        elif reference not in element_ids:
                            error(reference_path, f'element "{reference}" does not exist in this scene')

    return errors


def main():
    files = sorted(INPUT_DIR.glob("*.json")) if INPUT_DIR.is_dir() else []
    for path in files:
        try:
            with path.open(encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                print(f"[INVALID] {path.name}")
                print(f"$: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
            else:
                print(f"[INVALID] {path.name}")
                print("$: file must be UTF-8 encoded")
            continue

        errors = validate_project(data)
        if errors:
            print(f"[INVALID] {path.name}")
            for validation_error in errors:
                print(validation_error)
        else:
            print(f"[VALID] {path.name}")


if __name__ == "__main__":
    main()
