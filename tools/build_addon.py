"""Package the add-on, optionally embedding the project's public desktop OAuth client."""
import argparse
import json
from pathlib import Path
import tomllib
from zipfile import ZipFile, ZIP_DEFLATED


def build(output, client_path=None):
    root = Path(__file__).resolve().parents[1] / "addon/runpod_render"
    version = tomllib.loads((root / "blender_manifest.toml").read_text(encoding="utf-8"))["version"]
    client = None
    if client_path:
        data = json.loads(Path(client_path).read_text(encoding="utf-8"))
        client = data.get("installed", {})
        if not client.get("client_id", "").endswith(".apps.googleusercontent.com") or not client.get("client_secret"):
            raise ValueError("A project-owned Google Desktop OAuth client is required")
        # Desktop clients are public clients. Never package user tokens, RunPod keys or arbitrary JSON fields.
        client = {"installed": {key: client[key] for key in ("client_id", "client_secret")}}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"runpod_render-{version}.zip"
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in sorted(root.iterdir()):
            if path.suffix == ".py" or path.name == "blender_manifest.toml":
                archive.write(path, path.name)
        if client:
            archive.writestr("google_client.json", json.dumps(client))
    print(target)
    if not client:
        print("Development build: Google sign-in uses the user's existing Desktop OAuth JSON.")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--google-client", help="Project-owned Desktop OAuth client for a public build")
    args = parser.parse_args()
    build(args.output, args.google_client)
