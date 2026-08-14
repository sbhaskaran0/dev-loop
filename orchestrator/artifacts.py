"""Stage-artifact IO and validation.

Stages don't parse structured data out of a model's chat text — each prompt
tells the agent to WRITE its output to an absolute artifact path, and the
orchestrator validates the file afterward. Validation failures produce a
correction note the stage can retry with once.
"""
import json
from pathlib import Path


class ArtifactError(Exception):
    pass


def read_json(path: Path, required_keys: tuple[str, ...] = ()) -> dict | list:
    if not path.exists():
        raise ArtifactError(f"expected artifact was not written: {path}")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ArtifactError(f"{path.name} is not valid JSON: {e}")
    if required_keys:
        if not isinstance(obj, dict):
            raise ArtifactError(f"{path.name}: expected a JSON object")
        missing = [k for k in required_keys if k not in obj]
        if missing:
            raise ArtifactError(f"{path.name}: missing keys {missing}")
    return obj


def read_text(path: Path, min_chars: int = 1) -> str:
    if not path.exists():
        raise ArtifactError(f"expected artifact was not written: {path}")
    text = path.read_text(encoding="utf-8")
    if len(text.strip()) < min_chars:
        raise ArtifactError(f"{path.name}: suspiciously empty")
    return text


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def correction_note(error: Exception) -> str:
    return ("\n\nIMPORTANT — your previous attempt failed artifact "
            f"validation: {error}. Fix the problem and write the artifact "
            "file again, exactly to the path and schema specified above.")
