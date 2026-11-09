import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

import runpod
from transport import Drive


def handler(job):
    spec = job["input"]
    if spec.get("probe"):
        version = subprocess.check_output(["blender", "--version"], text=True).splitlines()[0]
        gpu = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], text=True
        ).strip()
        return {"blender": version, "gpu": gpu}
    drive = Drive(*(os.environ[key] for key in
                    ("DRIVE_CLIENT_ID", "DRIVE_CLIENT_SECRET", "DRIVE_REFRESH_TOKEN")))
    folder, state_id = (spec[key] for key in ("folder", "state"))
    for identifier in (folder, state_id, spec["source"]):
        if not re.fullmatch(r"[\w-]+", identifier, flags=re.ASCII):
            raise ValueError("Invalid Drive identifier")
    state = drive.read_status(state_id)
    saved = state.setdefault("files", {})
    frames = range(spec["start"], spec["end"] + 1, spec["step"])
    frame = None

    def report(stage, **details):
        state.update(stage=stage, frame=frame, updated=time.time(), **details)
        drive.status_file(state_id, state)

    try:
        report("preparing", error="")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "scene.blend"
            drive.download(spec["source"], source)
            for frame in frames:
                if str(frame) in saved:
                    continue
                report("rendering")
                prefix = root / f"frame_{frame:04d}"
                log = root / "blender.log"
                with log.open("w") as stream:
                    process = subprocess.run(
                        ["blender", "--background", "--factory-startup", "--disable-autoexec",
                         str(source), "--python-exit-code", "1", "--python", "/app/render.py",
                         "--", spec["scene"], str(frame), str(prefix)],
                        stdout=stream, stderr=subprocess.STDOUT,
                    )
                files = list(root.glob(prefix.name + ".*"))
                if process.returncode or len(files) != 1:
                    with log.open("rb") as stream:
                        stream.seek(max(0, log.stat().st_size - 2500))
                        error = stream.read().decode(errors="replace")
                    raise RuntimeError(error or "Blender did not produce an output file")
                report("uploading")
                image = files[0]
                saved[str(frame)] = {"id": drive.upload(image, folder), "name": image.name}
                report("saved")
                image.unlink()
        frame = None
        report("completed")
    except Exception as error:
        try:
            report("failed", error=str(error)[:2500], failed_stage=state["stage"])
        except Exception:
            pass
        raise
    return {"folder": folder, "state": state_id}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
