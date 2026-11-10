import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser

import bpy
from bpy.props import IntProperty, StringProperty

from .transport import Drive, api
from .oauth import authorize

BASE = "https://api.runpod.ai/v2/"
busy = False
message = ""
REFERENCE_RATE = 0.75
TERMINAL = {"completed", "failed", "cancelled", "timed_out"}
ENGINES = {"CYCLES": "Cycles", "BLENDER_EEVEE": "EEVEE", "BLENDER_EEVEE_NEXT": "EEVEE"}
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
    busy, message = True, "Workingâ€¦"
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
    destination: StringProperty(name="Download folder", subtype="DIR_PATH")

    def draw(self, context):
        for name in ("api_key", "endpoint", "oauth_file", "destination"):
            self.layout.prop(self, name)
        actions = self.layout.column()
        actions.enabled = not busy
        actions.operator("runpod_render.connect_drive")
        if credentials_path().exists():
            actions.operator("runpod_render.worker_settings")
        if message:
            self.layout.label(text=message[:160])


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


def queue_job(drive, folder, spec, base, key, history, filename, output_settings):
    initial = dict(stage="queued", frame=None, files={}, updated=time.time())
    with tempfile.TemporaryDirectory() as directory:
        status_path = Path(directory) / "status.json"
        status_path.write_text(json.dumps(initial), encoding="utf-8")
        spec = dict(spec, folder=folder, state=drive.upload(status_path, folder))
    jobs = load_jobs(history)
    job = dict(spec=spec, base=base, status=initial, filename=filename,
               output_settings=output_settings)
    reply = api(base + "/run", key, {
        "input": spec, "policy": {"executionTimeout": 14400000, "ttl": 86400000},
    })
    job["id"] = reply["id"]
    jobs.insert(0, job)
    save_jobs(history, jobs)


def refresh_jobs():
    if busy or not credentials_path().exists():
        return 60
    path = history_path()
    jobs = load_jobs(path)
    active = [job for job in jobs if job["status"]["stage"] not in TERMINAL]
    if not active:
        return 60
    drive, _ = drive_client()
    key = prefs().api_key

    def refresh():
        for job in active:
            try:
                job["status"] = drive.read_status(job["spec"]["state"])
                job.pop("status_error", None)
            except OSError as error:
                job["status_error"] = str(error)
            if key and job.get("id"):
                try:
                    remote = api(job["base"] + "/status/" + job["id"], key)
                    job["runpod"] = {name: remote[name] for name in
                                     ("delayTime", "executionTime", "status") if name in remote}
                    stage = remote.get("status", "")
                    if stage in {"FAILED", "CANCELLED", "TIMED_OUT"}:
                        job["status"].update(stage=stage.lower(),
                                             error=str(remote.get("error", stage)))
                except OSError:
                    pass
        save_jobs(path, jobs)

    run(refresh)
    return 60


def open_default(path):
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def import_compositor(scene, paths):
    if hasattr(scene, "compositing_node_group"):
        if scene.compositing_node_group is None:
            scene.compositing_node_group = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
        tree = scene.compositing_node_group
    else:
        scene.use_nodes = True
        tree = scene.node_tree
    for index, path in enumerate(paths):
        node = tree.nodes.new("CompositorNodeImage")
        node.image = bpy.data.images.load(str(path), check_existing=True)
        node.location = (-320, -index * 300)


def render_report(job):
    spec, state = job["spec"], job["status"]
    timing = state.get("timings", {})
    remote = job.get("runpod", {})
    elapsed = remote.get("executionTime", timing.get("worker_seconds", 0) * 1000) / 1000
    lines = [
        "RunPod Render Report", f"File: {job.get('filename', spec['scene'])}",
        f"Scene: {spec['scene']}", f"Job: {job.get('id', 'Unavailable')}",
        f"Endpoint: {job['base'].rsplit('/', 1)[-1]}",
        f"Frames: {spec['start']}â€“{spec['end']} (step {spec['step']})",
        f"Status: {state['stage']}", f"GPU: {state.get('gpu', 'Unavailable')}",
        f"Output: {job.get('output_settings', 'See uploaded scene')}",
        f"Reference rate: USD {REFERENCE_RATE:.2f}/hour",
        "Billed cost and separate startup/shutdown costs: unavailable",
    ]
    if "delayTime" in remote:
        lines.append(f"Queue: {remote['delayTime'] / 1000:.2f} s")
    if elapsed:
        lines.extend([f"Worker execution: {elapsed:.2f} s",
                      f"Estimated execution cost: USD {elapsed * REFERENCE_RATE / 3600:.5f}"])
    if "scene_download_seconds" in timing:
        lines.append(f"Scene download: {timing['scene_download_seconds']:.2f} s")
    if state.get("error"):
        lines.append(f"Error: {state['error']}")
    for frame, artifact in sorted(state["files"].items(), key=lambda item: int(item[0])):
        parts = [f"Frame {frame}: {artifact['name']}"]
        for field, label in (("render_and_save_seconds", "render and save"),
                             ("blender_process_seconds", "Blender process"),
                             ("upload_seconds", "upload")):
            if field in artifact:
                parts.append(f"{label} {artifact[field]:.2f} s")
        if "render_and_save_seconds" in artifact:
            parts.append(f"render and save estimate USD {artifact['render_and_save_seconds'] * REFERENCE_RATE / 3600:.5f}")
        lines.append(" | ".join(parts))
    return "\n".join(lines) + "\n"


class RUNPOD_Submit(bpy.types.Operator):
    bl_idname = "runpod_render.submit"
    bl_label = "Send render to RunPod"
    mode: StringProperty()

    def execute(self, context):
        scene = context.scene
        if not bpy.data.filepath or not scene.camera:
            self.report({"ERROR"}, "Save the scene and set a camera")
            return {"CANCELLED"}
        if scene.render.engine not in ENGINES:
            self.report({"ERROR"}, "Select Cycles or EEVEE")
            return {"CANCELLED"}
        if scene.render.image_settings.file_format not in images:
            self.report({"ERROR"}, "Select a supported image sequence format (video is pending)")
            return {"CANCELLED"}
        dependencies = bpy.utils.blend_paths(absolute=True, packed=False, local=False)
        bundled_assets = Path(bpy.utils.system_resource("DATAFILES", path="assets")).resolve()
        # The worker disables script auto-execution. Text Editor source paths
        # are not needed by the native render.
        text_paths = {
            Path(bpy.path.abspath(text.filepath, library=text.library)).resolve()
            for text in bpy.data.texts if text.filepath
        }
        dependencies = [
            path for path in dependencies
            if Path(path).resolve() not in text_paths
            and not Path(path).resolve().is_relative_to(bundled_assets)
        ]
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
        filename = Path(bpy.data.filepath).stem
        output_settings = (
            f"{ENGINES[scene.render.engine]} · {scene.render.resolution_x} × {scene.render.resolution_y} · "
            f"{scene.render.resolution_percentage}% · {scene.render.image_settings.file_format} · "
            f"{scene.render.fps / scene.render.fps_base:g} fps"
        )
        name = scene.name
        start, end, step = (scene.frame_start, scene.frame_end, scene.frame_step)
        if self.mode == "still":
            start, end, step = scene.frame_current, scene.frame_current, 1
        spec = dict(scene=name, start=start, end=end, step=step)

        def submit():
            try:
                folder = drive.unique_folder(filename, parent)
                spec["source"] = drive.upload(blend, folder)
                queue_job(drive, folder, spec, base, key, history, filename, output_settings)
            finally:
                temporary.cleanup()

        def done(_):
            global message
            message = "Submitted. You can close Blender."

        run(submit, done)
        return {"FINISHED"}


class RUNPOD_Jobs(bpy.types.Operator):
    bl_idname = "runpod_render.jobs"
    bl_label = "Render job action"
    action: StringProperty()
    state_id: StringProperty()
    start: IntProperty(name="Start frame")
    end: IntProperty(name="End frame")
    step: IntProperty(name="Frame step", min=1, default=1)

    def invoke(self, context, event):
        if self.action != "reuse":
            return self.execute(context)
        scene = context.scene
        self.start, self.end, self.step = scene.frame_start, scene.frame_end, scene.frame_step
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.label(text="Render from the saved Drive copy")
        for name in ("start", "end", "step"):
            self.layout.prop(self, name)

    def execute(self, context):
        path = history_path()
        jobs = load_jobs(path)
        job = next((item for item in jobs if item["spec"]["state"] == self.state_id), None)
        if job is None or busy:
            return {"CANCELLED"}
        action = self.action
        if action == "open_drive":
            webbrowser.open("https://drive.google.com/drive/folders/" + job["spec"]["folder"])
            return {"FINISHED"}
        destination = prefs().destination
        if action in {"open", "compositor", "report"} and not destination:
            self.report({"ERROR"}, "Set a download folder in the add-on preferences")
            return {"CANCELLED"}
        if action == "reuse" and self.end < self.start:
            self.report({"ERROR"}, "End frame must be at or after start frame")
            return {"CANCELLED"}
        output = Path(bpy.path.abspath(destination)) if destination else None
        if action == "report":
            folder = output / job["spec"]["folder"]
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / "render-report.txt"
            target.write_text(render_report(job), encoding="utf-8")
            self.report({"INFO"}, f"Report saved to {target}")
            return {"FINISHED"}

        drive, parent = drive_client()
        key = prefs().api_key
        scene = context.scene
        frame_range = dict(start=self.start, end=self.end, step=self.step)

        def perform():
            if action in {"reuse", "rerender"}:
                spec = dict(job["spec"])
                if action == "reuse":
                    spec.update(frame_range)
                filename = job.get("filename", spec["scene"])
                folder = drive.unique_folder(filename, parent)
                queue_job(drive, folder, spec, job["base"], key, path, filename,
                          job.get("output_settings", "See uploaded scene"))
                return []
            if action == "retry":
                reply = api(job["base"] + "/run", key, {
                    "input": job["spec"], "policy": {"executionTimeout": 14400000, "ttl": 86400000},
                })
                job["id"] = reply["id"]
                job.pop("runpod", None)
                job["status"].update(stage="queued", updated=time.time(), error="")
                save_jobs(path, jobs)
                return []
            folder = output / job["spec"]["folder"]
            folder.mkdir(parents=True, exist_ok=True)
            status = drive.read_status(job["spec"]["state"])
            paths = []
            for _, artifact in sorted(status["files"].items(), key=lambda item: int(item[0])):
                target = folder / Path(artifact["name"]).name
                partial = target.with_suffix(target.suffix + ".part")
                drive.download(artifact["id"], partial)
                partial.replace(target)
                paths.append(target)
            return paths

        def done(paths):
            if action == "compositor" and paths:
                import_compositor(scene, paths)
            elif action == "open" and paths:
                open_default(paths[0])

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
        connected = credentials_path().exists()
        layout.label(text="Google Drive connected" if connected else "Google Drive not connected",
                     icon="CHECKMARK" if connected else "ERROR")
        layout.label(text=f"Serverless endpoint: {settings.endpoint or 'Not configured'}")
        engine = ENGINES.get(scene.render.engine, "Unsupported")
        layout.label(text=f"Worker render engine: {engine}")
        layout.label(text=f"{scene.render.resolution_x} Ã— {scene.render.resolution_y} Â· "
                          f"{scene.render.resolution_percentage}% Â· "
                          f"{scene.render.image_settings.file_format}")
        layout.label(text=f"Frames {scene.frame_start}â€“{scene.frame_end} Â· "
                          f"Step {scene.frame_step} Â· FPS {scene.render.fps / scene.render.fps_base:g}")
        actions = layout.column()
        actions.enabled = connected and bool(settings.endpoint and settings.api_key)
        actions.operator("runpod_render.submit", text="Render current frame",
                         icon="RENDER_STILL", depress=True).mode = "still"
        actions.operator("runpod_render.submit", text="Render animation",
                         icon="RENDER_ANIMATION", depress=True).mode = "animation"
        if message:
            layout.label(text=message[:160])
        for job in load_jobs(history_path()):
            spec, state = job["spec"], job["status"]
            box = layout.box()
            count = len(range(spec["start"], spec["end"] + 1, spec["step"]))
            stage = state["stage"]
            if stage in {"queued", "preparing", "rendering", "uploading", "saved"} and time.time() - state["updated"] > 180:
                stage += " Â· no recent update"
            box.label(text=f"{job.get('filename', spec['scene'])} Â· {stage} Â· {len(state['files'])}/{count}")
            if state["frame"] is not None:
                box.label(text=f"Frame {state['frame']}")
            box.label(text=time.strftime("Updated %Y-%m-%d %H:%M:%S", time.localtime(state["updated"])))
            if state.get("error") or job.get("status_error"):
                box.label(text=str(state.get("error") or job["status_error"])[-110:], icon="ERROR")
            row = box.row()
            options = [("open_drive", "Open Drive"), ("report", "Download full report")]
            if state["files"]:
                options.extend([("open", "Open"), ("compositor", "Import Compositor")])
            if state["stage"] in TERMINAL:
                options.append(("reuse", "Reuse uploaded scene"))
            if state["stage"] == "completed":
                options.append(("rerender", "Render again"))
            if state["stage"] in {"failed", "cancelled", "timed_out"}:
                options.append(("retry", "Retry pending"))
            for index, (action, label) in enumerate(options):
                if index and index % 2 == 0:
                    row = box.row()
                operation = row.operator("runpod_render.jobs", text=label)
                operation.action, operation.state_id = action, spec["state"]


classes = (RUNPOD_Preferences, RUNPOD_Connect, RUNPOD_WorkerSettings, RUNPOD_Submit,
           RUNPOD_Jobs, RUNPOD_PT_Render)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.timers.register(refresh_jobs, first_interval=1, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(refresh_jobs):
        bpy.app.timers.unregister(refresh_jobs)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
