"""Persistent job ownership and atomic updates, independent of Blender's UI."""
import hashlib
import json
import os
from pathlib import Path
import threading

LOCK = threading.RLock()
TERMINAL = {"completed", "failed", "cancelled", "timed_out"}


def project_id(filepath):
    if not filepath:
        return ""
    # Full paths distinguish identically named files and Save As copies.
    path = os.path.normcase(str(Path(filepath).resolve()))
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def load_jobs(path):
    with LOCK:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def save_jobs(path, jobs):
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".tmp")
        partial.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
        partial.replace(path)


def update_job(path, state_id, change):
    with LOCK:
        jobs = load_jobs(path)
        for job in jobs:
            if job["spec"]["state"] == state_id:
                change(job)
                save_jobs(path, jobs)
                return job
    raise ValueError("Render job no longer exists")


def add_job(path, job):
    with LOCK:
        jobs = load_jobs(path)
        jobs.insert(0, job)
        save_jobs(path, jobs)


def for_project(jobs, identity):
    return [job for job in jobs if identity and job.get("project_id") == identity]


def progress(job):
    spec = job["spec"]
    frames = range(spec["start"], spec["end"] + 1, spec["step"])
    done = sum(str(frame) in job["status"].get("files", {}) for frame in frames)
    return done, len(frames)


def reconcile(job, state, remote):
    """Provider terminal states win over stale Drive writes after cancellation."""
    job["status"] = state
    if remote:
        job["runpod"] = {key: remote[key] for key in
                         ("delayTime", "executionTime", "status") if key in remote}
        stage = remote.get("status", "").lower()
        if stage in {"failed", "cancelled", "timed_out"}:
            job["status"].update(stage=stage, error=str(remote.get("error", stage)))
        elif stage == "completed" and state.get("stage") != "completed":
            # A completed provider request is not proof that every frame was uploaded.
            done, total = progress(job)
            if done == total:
                job["status"]["stage"] = "completed"
        if stage in TERMINAL:
            job.pop("cancel_requested", None)

