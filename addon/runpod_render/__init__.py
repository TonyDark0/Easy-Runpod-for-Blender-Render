import json
import os
from pathlib import Path
import tempfile
import threading
import time
import webbrowser

import bpy
from bpy.props import FloatProperty, StringProperty

from .transport import Drive, api
from .oauth import authorize

BASE = "https://api.runpod.ai/v2/"
busy = False
message = ""
probe = ""
images = {"PNG", "OPEN_EXR", "OPEN_EXR_MULTILAYER", "JPEG", "TIFF"}


def prefs():
    return bpy.context.preferences.addons[__package__].preferences


def history_path():
    return Path(bpy.utils.user_resource("CONFIG")) / "runpod_render_jobs.json"


def load_jobs(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def save_jobs(path, jobs):
    partial = path.with_suffix(".tmp")
    partial.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    partial.replace(path)


def run(operation, finished=None):
    global busy, message
    busy, message = True, "Working…"
    result = []

    def work():
        try:
            result.append((True, operation()))
        except Exception as error:
            result.append((False, str(error)))

    def finish():
        global busy, message
        if not result:
            return 0.25
        success, value = result[0]
        busy, message = False, "Ready" if success else value
        if success and finished:
            try:
                finished(value)
            except Exception as error:
                message = str(error)
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type == "PROPERTIES":
                    area.tag_redraw()
        return None

    threading.Thread(target=work, daemon=True).start()
    bpy.app.timers.register(finish, persistent=True)


class RUNPOD_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    api_key: StringProperty(name="RunPod API key", subtype="PASSWORD")
    endpoint: StringProperty(name="Endpoint ID")
    oauth_file: StringProperty(name="Google desktop OAuth JSON", subtype="FILE_PATH")
    hourly_rate: FloatProperty(name='Worker rate (USD/hour)', min=0, precision=3)
    destination: StringProperty(name="Download folder", subtype="DIR_PATH")

    def draw(self, context):
        for name in ("api_key", "endpoint", "oauth_file", "destination", "hourly_rate"):
            self.layout.prop(self, name)
        self.layout.operator("runpod_render.connect_drive")


def credentials_path():
    return Path(bpy.utils.user_resource("CONFIG")) / "runpod_drive_credentials.json"


def drive_client():
    data = json.loads(credentials_path().read_text(encoding="utf-8"))
    return Drive(data["client_id"], data["client_secret"], data["refresh_token"]), data["folder"]


class RUNPOD_Connect(bpy.types.Operator):
    bl_idname = "runpod_render.connect_drive"
    bl_label = "Connect Google Drive"

    def execute(self, context):
        path = bpy.path.abspath(prefs().oauth_file)
        target = credentials_path()

        def connect():
            data = authorize(path)
            drive = Drive(data["client_id"], data["client_secret"], data["refresh_token"])
            data["folder"] = drive.folder("RunPod Renders", "root")
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream)

        run(connect)
        return {"FINISHED"}


class RUNPOD_WorkerSettings(bpy.types.Operator):
    bl_idname = "runpod_render.worker_settings"
    bl_label = "Copy worker credentials"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        data = json.loads(credentials_path().read_text(encoding="utf-8"))
        context.window_manager.clipboard = json.dumps({
            "DRIVE_CLIENT_ID": data["client_id"],
            "DRIVE_CLIENT_SECRET": data["client_secret"],
            "DRIVE_REFRESH_TOKEN": data["refresh_token"],
        })
        return {"FINISHED"}


def endpoint_settings():
    configuration = prefs()
    endpoint = configuration.endpoint.strip()
    if not endpoint.isascii() or not endpoint.replace("-", "").isalnum():
        raise ValueError("Enter a valid RunPod endpoint ID")
    if not configuration.api_key:
        raise ValueError("Enter a RunPod API key")
    return BASE + endpoint, configuration.api_key


class RUNPOD_Probe(bpy.types.Operator):
    bl_idname = "runpod_render.probe"
    bl_label = "Test worker (may incur GPU charges)"

    def execute(self, context):
        base, key = endpoint_settings()

        def check():
            reply = api(base + "/runsync", key, {"input": {"probe": True}})
            if reply["status"] != "COMPLETED":
                raise RuntimeError(reply.get("error", reply["status"]))
            output = reply["output"]
            return output["blender"] + " · " + output["gpu"]

        def done(value):
            global probe
            probe = value

        run(check, done)
        return {"FINISHED"}


class RUNPOD_Submit(bpy.types.Operator):
    bl_idname = "runpod_render.submit"
    bl_label = "Send render to RunPod"
    mode: StringProperty()

    def execute(self, context):
        scene = context.scene
        if not bpy.data.filepath or scene.render.engine != "CYCLES" or not scene.camera:
            self.report({"ERROR"}, "Save the scene, select Cycles, and set a camera")
            return {"CANCELLED"}
        if scene.render.image_settings.file_format not in images:
            self.report({"ERROR"}, "Select a supported image sequence format (video is pending)")
            return {"CANCELLED"}
        dependencies = bpy.utils.blend_paths(absolute=True, packed=False, local=False)
        bundled_assets = Path(bpy.utils.system_resource("DATAFILES", path="assets")).resolve()
        dependencies = [path for path in dependencies
                        if not Path(path).resolve().is_relative_to(bundled_assets)]
        if dependencies:
            self.report({"ERROR"}, "Pack external resources: " + ", ".join(dependencies[:3]))
            return {"CANCELLED"}
        base, key = endpoint_settings()
        drive, parent = drive_client()
        history = history_path()
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        blend = root / "scene.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
        hourly_rate = prefs().hourly_rate
        name = scene.name
        start, end, step = (scene.frame_start, scene.frame_end, scene.frame_step)
        if self.mode == "still":
            start, end, step = scene.frame_current, scene.frame_current, 1
        spec = dict(scene=name, start=start, end=end, step=step)

        def submit():
            try:
                folder = drive.folder(f"{name} · {time.strftime('%Y-%m-%d %H-%M-%S')}", parent)
                source = drive.upload(blend, folder)
                status = root / "status.json"
                initial = dict(stage="queued", frame=None, files={}, updated=time.time())
                status.write_text(json.dumps(initial), encoding="utf-8")
                state = drive.upload(status, folder)
                spec.update(folder=folder, source=source, state=state)
                jobs = load_jobs(history)
                job = dict(spec=spec, base=base, status=initial, hourly_rate=hourly_rate)
                jobs.insert(0, job)
                save_jobs(history, jobs)
                reply = api(base + "/run", key, {"input": spec, "policy": {"executionTimeout": 14400000, "ttl": 86400000}})
                job["id"] = reply["id"]
                save_jobs(history, jobs)
            finally:
                temporary.cleanup()

        def done(_):
            global message
            message = "Submitted. You can close Blender."

        run(submit, done)
        return {"FINISHED"}


class RUNPOD_Jobs(bpy.types.Operator):
    bl_idname = "runpod_render.jobs"
    bl_label = "Update jobs"
    action: StringProperty(default="refresh")
    state_id: StringProperty()

    def execute(self, context):
        path = history_path()
        drive, _ = drive_client()
        action = self.action
        jobs = load_jobs(path)
        job = next((item for item in jobs if item["spec"]["state"] == self.state_id), None)
        key = prefs().api_key
        destination = prefs().destination
        if action == "open":
            webbrowser.open("https://drive.google.com/drive/folders/" + job["spec"]["folder"])
            return {"FINISHED"}
        if action == "download" and not destination:
            self.report({"ERROR"}, "Choose a download folder")
            return {"CANCELLED"}
        output = Path(bpy.path.abspath(destination)) if destination else None

        def perform():
            if action == "refresh":
                failures = []
                for item in jobs:
                    try:
                        item["status"] = drive.read_status(item["spec"]["state"])
                        item.pop("status_error", None)
                    except Exception as error:
                        failures.append(str(error))
                        item["status_error"] = str(error)
                save_jobs(path, jobs)
                if failures:
                    raise RuntimeError(failures[0])
            elif action == "retry":
                reply = api(job["base"] + "/run", key, {"input": job["spec"], "policy": {"executionTimeout": 14400000, "ttl": 86400000}})
                job["id"] = reply["id"]
                job["status"].update(stage="queued", updated=time.time())
                save_jobs(path, jobs)
            else:
                folder = output / job["spec"]["folder"]
                folder.mkdir(parents=True, exist_ok=True)
                status = drive.read_status(job["spec"]["state"])
                first = None
                for artifact in status["files"].values():
                    target = folder / Path(artifact["name"]).name
                    partial = target.with_suffix(target.suffix + ".part")
                    drive.download(artifact["id"], partial)
                    partial.replace(target)
                    first = first or str(target)
                return first

        def done(first):
            if first:
                image = bpy.data.images.load(first, check_existing=True)
                bpy.ops.render.view_show()
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == "IMAGE_EDITOR":
                            area.spaces.active.image = image

        run(perform, done)
        return {"FINISHED"}


class RUNPOD_PT_Render(bpy.types.Panel):
    bl_label = "RunPod Render"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        settings = prefs()
        scene = context.scene
        layout.enabled = not busy
        connection = layout.box()
        for name in ("api_key", "endpoint", "oauth_file", "destination", "hourly_rate"):
            connection.prop(settings, name)
        connection.operator("runpod_render.connect_drive")
        if credentials_path().exists():
            connection.label(text="Google Drive connected")
            connection.operator("runpod_render.worker_settings")
        connection.operator("runpod_render.probe")
        if probe:
            connection.label(text=probe)
        layout.label(text=f"{scene.render.resolution_x} × {scene.render.resolution_y} · "
                          f"{scene.render.resolution_percentage}% · "
                          f"{scene.render.image_settings.file_format}")
        layout.label(text=f"Frames {scene.frame_start}–{scene.frame_end} · "
                          f"Step {scene.frame_step} · FPS {scene.render.fps / scene.render.fps_base:g}")
        layout.operator("runpod_render.submit", text="Render current frame").mode = "still"
        layout.operator("runpod_render.submit", text="Render animation").mode = "animation"
        layout.operator("runpod_render.jobs")
        if message:
            layout.label(text=message[:160])
        for job in load_jobs(history_path()):
            spec, state = job["spec"], job["status"]
            box = layout.box()
            count = len(range(spec["start"], spec["end"] + 1, spec["step"]))
            stage = state["stage"]
            if stage in {"preparing", "rendering", "uploading", "saved"} and time.time() - state["updated"] > 180:
                stage += " · no recent update"
            box.label(text=f"{spec['scene']} · {stage} · {len(state['files'])}/{count}")
            if state["frame"] is not None:
                box.label(text=f"Frame {state['frame']}")
            box.label(text=time.strftime("Updated %Y-%m-%d %H:%M:%S", time.localtime(state["updated"])))
            timings = state.get('timings', {})
            elapsed = timings.get('worker_seconds', 0)
            rate = job.get('hourly_rate', 0)
            if elapsed:
                box.label(text=f'Worker execution: {elapsed:.2f} s')
                if rate:
                    box.label(text=f'Estimated execution cost: USD {elapsed * rate / 3600:.5f}')
            measured = [item for item in state['files'].values() if 'render_and_save_seconds' in item]
            if measured:
                seconds = sum(item['render_and_save_seconds'] for item in measured)
                box.label(text=f'Render and save: {seconds:.2f} s total · {seconds / len(measured):.2f} s/frame')
            if state.get("error"):
                box.label(text=f"{state.get('failed_stage', '')}: {state['error'][-110:]}")
            row = box.row()
            for action, label in [("open", "Open Drive"), ("download", "Download and view"),
                                  ("retry", "Retry pending")]:
                if action == "retry" and state["stage"] != "failed":
                    continue
                if action == "download" and not state["files"]:
                    continue
                operation = row.operator("runpod_render.jobs", text=label)
                operation.action, operation.state_id = action, spec["state"]


classes = (RUNPOD_Preferences, RUNPOD_Connect, RUNPOD_WorkerSettings, RUNPOD_Probe, RUNPOD_Submit,
           RUNPOD_Jobs, RUNPOD_PT_Render)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


