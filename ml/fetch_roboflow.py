"""Download a public Roboflow Universe dataset version in YOLO format, with a license check.

    uv run python ml/fetch_roboflow.py WORKSPACE/PROJECT/VERSION

The API key (free account: roboflow.com -> Settings -> API Keys) is read from the
ROBOFLOW_API_KEY environment variable, else from ~/.config/vantage/roboflow_api_key
(outside the repository, so it cannot be committed). Never put the key in the repo.

The ID is the last part of a Universe URL:
https://universe.roboflow.com/WORKSPACE/PROJECT/dataset/VERSION

Writes ml/external/WORKSPACE__PROJECT__vVERSION/ (git-ignored) with the YOLO export and
SOURCE.json, and appends attribution to ml/DATA_SOURCES.md (committed). Licenses that
forbid commercial use or derivatives, or are missing, are refused unless --allow-license
is given explicitly, because a model trained on them may ship in the app.
"""
import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.roboflow.com"
EXTERNAL = ROOT / "ml" / "external"
SOURCES = ROOT / "ml" / "DATA_SOURCES.md"
KEY_FILE = Path.home() / ".config" / "vantage" / "roboflow_api_key"


def api_key():
    """Key from the environment, else the private key file; None if neither is set."""
    key = os.environ.get("ROBOFLOW_API_KEY", "").strip()
    if not key and KEY_FILE.is_file():
        key = KEY_FILE.read_text().strip()
    return key or None


def license_problem(name):
    """None if the license allows training a shippable model, else the reason."""
    if not name or not str(name).strip():
        return "no license stated"
    text = str(name).upper().replace("-", " ")
    if "NC" in text.split() or "NONCOMMERCIAL" in text.replace(" ", ""):
        return f"non-commercial license ({name})"
    if "ND" in text.split() or "NODERIVATIVES" in text.replace(" ", ""):
        return f"no-derivatives license ({name})"
    if text.strip() in {"PRIVATE", "UNKNOWN", "OTHER"}:
        return f"unclear license ({name})"
    return None


def parse_id(dataset_id):
    parts = dataset_id.strip("/").split("/")
    if len(parts) != 3 or not parts[2].isdigit():
        raise ValueError("Dataset ID must be WORKSPACE/PROJECT/VERSION, e.g. acme/pickleball-ball/2")
    return parts[0], parts[1], int(parts[2])


def get_json(url, api_key):
    query = urllib.parse.urlencode({"api_key": api_key})
    with urllib.request.urlopen(f"{url}?{query}", timeout=60) as response:
        return json.load(response)


def export_link(workspace, project, version, api_key, fmt, wait_s=300):
    """Roboflow generates exports on demand; poll until the download link exists."""
    deadline = time.monotonic() + wait_s
    while True:
        data = get_json(f"{API}/{workspace}/{project}/{version}/{fmt}", api_key)
        link = data.get("export", {}).get("link")
        if link:
            return link
        if time.monotonic() > deadline:
            raise RuntimeError(f"Export not ready after {wait_s} s: {data}")
        time.sleep(5)


def append_attribution(entry):
    header = ("# External training data\n\nDatasets downloaded with `ml/fetch_roboflow.py`. "
              "Keep this file: CC BY licenses require attribution.\n\n"
              "| Dataset | License | Images | Classes | Retrieved |\n| --- | --- | ---: | --- | --- |\n")
    text = SOURCES.read_text() if SOURCES.exists() else header
    row = (f"| [{entry['id']}]({entry['url']}) | {entry['license']} | {entry['images']} | "
           f"{', '.join(entry['classes'])} | {entry['retrieved'][:10]} |\n")
    if f"[{entry['id']}]" not in text:
        SOURCES.write_text(text + row)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", help="WORKSPACE/PROJECT/VERSION")
    parser.add_argument("--format", default="yolov8", help="Roboflow export format (default yolov8)")
    parser.add_argument("--allow-license", help="explicitly accept this license string after reviewing it")
    parser.add_argument("--info", action="store_true", help="print project metadata and exit")
    args = parser.parse_args()
    key = api_key()
    if not key:
        parser.error(f"No Roboflow API key: set ROBOFLOW_API_KEY or write it to {KEY_FILE}.")
    workspace, project, version = parse_id(args.dataset)

    info = get_json(f"{API}/{workspace}/{project}", key).get("project", {})
    license_name = info.get("license")
    classes = sorted((info.get("classes") or {}).keys())
    print(json.dumps({"name": info.get("name"), "license": license_name, "images": info.get("images"),
                      "classes": info.get("classes"), "type": info.get("type")}, indent=2))
    if args.info:
        return
    problem = license_problem(license_name)
    if problem and args.allow_license != license_name:
        raise SystemExit(f"Refusing {args.dataset}: {problem}. Review it and pass "
                         f"--allow-license '{license_name}' only if this use is permitted.")

    destination = EXTERNAL / f"{workspace}__{project}__v{version}"
    if destination.exists():
        raise SystemExit(f"{destination} already exists; delete it to re-download.")
    link = export_link(workspace, project, version, key, args.format)
    print("Downloading export...")
    with urllib.request.urlopen(link, timeout=600) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    destination.mkdir(parents=True)
    archive.extractall(destination)
    entry = {"id": args.dataset, "url": f"https://universe.roboflow.com/{workspace}/{project}/dataset/{version}",
             "license": license_name, "images": info.get("images"), "classes": classes,
             "format": args.format, "retrieved": datetime.now(timezone.utc).isoformat()}
    (destination / "SOURCE.json").write_text(json.dumps(entry, indent=2) + "\n")
    append_attribution(entry)
    print(f"Saved {destination} and recorded attribution in {SOURCES.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
