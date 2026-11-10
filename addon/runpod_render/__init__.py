from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from zipfile import ZIP_DEFLATED, ZipFile

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.app.handlers import persistent

from .transport import Drive, api, check_cancel
from .oauth import authorize
from .cache_paths import cache_properties, point_caches
from .credentials import read_credentials, write_credentials
from .setup import CONTROL, endpoint_payload, gpu_selection, provision
from .jobs import (TERMINAL, add_job, for_project, load_jobs, progress, project_id,
                   reconcile, save_jobs, update_job)

BASE = "https://api.runpod.ai/v2/"
busy = False
message = ""
REFERENCE_RATE = 0.75
cancel_event = threading.Event()
operation_project = ""
operation_cancellable = False
connection_status = ""
connection_signature = None
snapshot_items = []
worker_quote = None
ENGINES = {"CYCLES": "Cycles", "BLENDER_EEVEE": "EEVEE", "BLENDER_EEVEE_NEXT": "EEVEE"}
images = {"PNG", "OPEN_EXR", "OPEN_EXR_MULTILAYER", "JPEG", "TIFF"}


def prefs():
    return bpy.context.preferences.addons[__package__].preferences


def history_path():
    return Path(bpy.utils.user_resource("CONFIG")) / "runpod_render_jobs.json"


def current_project():
    return project_id(bpy.data.filepath)


def project_jobs():
    return for_project(load_jobs(history_path()), current_project())


def run(operation, finished=None, *, label="Working...", cancellable=False):
    global busy, message, operation_project, operation_cancellable
    if busy:
        raise RuntimeError("Wait for the current operation to finish")
    busy, message = True, label
    operation_project = current_project()
    operation_cancellable = cancellable
    cancel_event.clear()
    result = []

    def work():
        try:
            result.append((True, operation()))
        except Exception as error:
            result.append((False, str(error)))

    def finish():
        global busy, message, operation_cancellable
        if not result:
            redraw()
            return 0.25
        success, value = result[0]
        busy, message = False, "Ready" if success else value
        operation_cancellable = False
        if success and finished:
            try:
                finished(value)
            except Exception as error:
                message = str(error)
        redraw()
        return None

    threading.Thread(target=work, daemon=True).start()
    bpy.app.timers.register(finish, persistent=True)


def redraw():
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type in {"PROPERTIES", "PREFERENCES"}:
                area.tag_redraw()


def phase(text):
    global message
    message = text
    check_cancel(cancel_event)


class RUNPOD_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    api_key: StringProperty(name="RunPod API key", subtype="PASSWORD")
    endpoint: StringProperty(name="Endpoint ID")
    oauth_file: StringProperty(name="Google desktop OAuth JSON", subtype="FILE_PATH")
    destination: StringProperty(name="Download folder", subtype="DIR_PATH")
    auto_download: BoolProperty(name="Automatically download results while Blender is open", default=False)
    drive_folder_name: StringProperty(name="Root folder name", default="RunPod Renders")
    advanced: BoolProperty(name="Advanced", default=False)
    show_legacy: BoolProperty(name="Unassigned jobs from older versions", default=False)
    timeout_minutes: IntProperty(name="Maximum job duration (minutes)", default=240, min=1, max=1440)
    gpu_profile: EnumProperty(name="GPU profile", items=[
        ("AMPERE_24", "24 GB - availability", "Full GPUs; MIG excluded"),
        ("ADA_24", "RTX 4090 - 24 GB", "RTX 4090 only")])
    disk_gb: IntProperty(name="Worker disk (GB)", default=50, min=20, max=500)
    managed_endpoint: StringProperty(options={"HIDDEN"})
    worker_description: StringProperty(options={"HIDDEN"})

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="RunPod connection", icon="NETWORK_DRIVE")
        box.prop(self, "api_key")
        actions = box.column()
        actions.enabled = not busy
        actions.operator("runpod_render.connection", text="Check RunPod connection").action = "check"
        box.label(text=connection_status or "Use Advanced to connect an existing Serverless endpoint")
        box = layout.box()
        box.label(text="Google Drive", icon="FILE_FOLDER")
        data = google_info()
        box.label(text=(data.get("email") or "Google Drive connected") if data else "Google Drive not connected",
                  icon="CHECKMARK" if data else "ERROR")
        box.prop(self, "drive_folder_name")
        actions = box.column()
        actions.enabled = not busy
        actions.operator("runpod_render.connect_drive", text="Reconnect Google Drive" if data else "Connect Google Drive")
        if data:
            actions.operator("runpod_render.connection", text="Open Drive folder").action = "drive"
            actions.operator("runpod_render.connection", text="Disconnect on this computer").action = "disconnect"
        box.label(text="Only files created or authorized for this app are accessible.")
        box = layout.box()
        box.label(text="Worker setup")
        box.prop(self, "gpu_profile")
        box.label(text="Worker Blender version: 4.5.4")
        box.prop(self, "disk_gb")
        controls = box.column()
        controls.enabled = not busy and bool(self.api_key) and bool(data)
        controls.operator("runpod_render.setup_worker", text="Review worker setup").review = True
        if worker_quote and worker_quote["profile"] == self.gpu_profile:
            box.label(text=worker_quote["label"])
            box.label(text=f"Serverless GPU rate: up to USD {worker_quote['rate']:.4f}/hour")
            box.label(text="0 active workers | 1 maximum worker | 5-second idle timeout")
            controls.operator("runpod_render.setup_worker", text=
                              "Update worker" if self.managed_endpoint else "Set up worker").review = False
        if self.worker_description:
            box.label(text=self.worker_description)
        box = layout.box()
        box.label(text="Usage limits")
        box.prop(self, "timeout_minutes")
        box.label(text="Automatic render retries: off. Retry missing frames manually.")
        box.label(text="Configure the endpoint for 0 active and 1 maximum worker.")
        box = layout.box()
        box.label(text="Downloads")
        box.prop(self, "destination")
        box.prop(self, "auto_download")
        layout.prop(self, "advanced", icon="TRIA_DOWN" if self.advanced else "TRIA_RIGHT", emboss=False)
        if self.advanced:
            box = layout.box()
            box.label(text="Existing worker / development setup")
            box.prop(self, "endpoint")
            box.prop(self, "oauth_file")
            box.label(text="Desktop OAuth JSON overrides the public app configuration.")
            if data:
                box.operator("runpod_render.worker_settings")
            box.prop(self, "show_legacy")
            if self.show_legacy:
                box.label(text="Assign old jobs explicitly; names alone cannot identify a file.")
                for job in load_jobs(history_path()):
                    if not job.get("project_id"):
                        row = box.row()
                        row.label(text=job.get("filename", job["spec"]["scene"]))
                        op = row.operator("runpod_render.jobs", text="Assign to current file")
                        op.action, op.state_id = "assign", job["spec"]["state"]
        if message:
            layout.label(text=message[:160])
        if busy and operation_cancellable:
            layout.operator("runpod_render.cancel", text="Cancel process", icon="CANCEL")


def credentials_path():
    return Path(bpy.utils.user_resource("CONFIG")) / "runpod_drive_credentials.json"


def drive_client():
    data = read_credentials(credentials_path())
    return Drive(data["client_id"], data["client_secret"], data["refresh_token"]), data["folder"]


def google_info():
    try:
        return read_credentials(credentials_path())
    except (OSError, ValueError, KeyError):
        return {}


class RUNPOD_Connect(bpy.types.Operator):
    bl_idname = "runpod_render.connect_drive"
    bl_label = "Connect Google Drive"

    def execute(self, context):
        path = bpy.path.abspath(prefs().oauth_file) if prefs().oauth_file else ""
        target = credentials_path()
        folder_name = prefs().drive_folder_name.strip() or "RunPod Renders"
        previous = google_info()

        def connect():
            data = authorize(path, cancel_event)
            drive = Drive(data["client_id"], data["client_secret"], data["refresh_token"])
            account = api("https://www.googleapis.com/drive/v3/about?fields=user", drive.token())["user"]
            data["email"] = account.get("emailAddress", "")
            data["permission_id"] = account.get("permissionId", "")
            if (previous.get("permission_id") == data["permission_id"] and data["permission_id"]
                    and previous.get("folder_name") == folder_name):
                data["folder"] = previous["folder"]
            else:
                data["folder"] = drive.folder(folder_name, "root")
            data["folder_name"] = folder_name
            check_cancel(cancel_event)
            write_credentials(target, data)

        def done(_):
            global message
            bpy.ops.wm.save_userpref()
            message = "Google Drive connected. Update your worker credentials before submitting new jobs."
        run(connect, done, label="Waiting for Google sign-in...", cancellable=True)
        return {"FINISHED"}


class RUNPOD_WorkerSettings(bpy.types.Operator):
    bl_idname = "runpod_render.worker_settings"
    bl_label = "Copy worker credentials"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        data = read_credentials(credentials_path())
        context.window_manager.clipboard = json.dumps({
            "DRIVE_CLIENT_ID": data["client_id"],
            "DRIVE_CLIENT_SECRET": data["client_secret"],
            "DRIVE_REFRESH_TOKEN": data["refresh_token"],
        })
        return {"FINISHED"}


class RUNPOD_SetupWorker(bpy.types.Operator):
    bl_idname = "runpod_render.setup_worker"
    bl_label = "Set up Serverless worker"
    bl_description = "Configure your own RunPod endpoint with zero permanent workers and Google Drive access"
    review: BoolProperty(default=True)

    def execute(self, context):
        settings = prefs()
        key, profile = settings.api_key, settings.gpu_profile
        if self.review:
            def inspect():
                catalog = api(CONTROL + "/catalog/gpus?product=SERVERLESS", key)
                gpu, rate, label = gpu_selection(catalog, profile)
                return dict(gpu=gpu, rate=rate, label=label, profile=profile,
                            checked_at=time.time())
            def done(quote):
                global worker_quote
                worker_quote = quote
            run(inspect, done, label="Checking current GPU pricing...")
            return {"FINISHED"}
        if not worker_quote or worker_quote["profile"] != profile or time.time() - worker_quote["checked_at"] > 300:
            self.report({"ERROR"}, "Review worker setup again to refresh GPU pricing")
            return {"CANCELLED"}
        if settings.endpoint and settings.endpoint != settings.managed_endpoint:
            self.report({"ERROR"}, "An existing endpoint is configured. Keep it, or clear its ID in Advanced before creating a separate managed worker.")
            return {"CANCELLED"}
        data = google_info()
        if not data:
            self.report({"ERROR"}, "Connect Google Drive first")
            return {"CANCELLED"}
        payload = endpoint_payload("Easy RunPod for Blender Render", worker_quote["gpu"],
                                   data, settings.timeout_minutes, settings.disk_gb)
        endpoint = settings.managed_endpoint
        description = worker_quote["label"] + " | Blender 4.5.4"
        def done(result):
            settings = prefs()
            settings.endpoint = result["id"]
            settings.managed_endpoint = result["id"]
            settings.worker_description = description
            bpy.ops.wm.save_userpref()
        run(lambda: provision(key, payload, endpoint), done, label="Configuring Serverless worker...")
        return {"FINISHED"}


def endpoint_settings():
    configuration = prefs()
    endpoint = configuration.endpoint.strip()
    if not endpoint.isascii() or not endpoint.replace("-", "").isalnum():
        raise ValueError("Enter a valid RunPod endpoint ID")
    if not configuration.api_key:
        raise ValueError("Enter a RunPod API key")
    return BASE + endpoint, configuration.api_key


def queue_job(drive, folder, spec, base, key, history, filename, output_settings,
              identity, timeout, metadata=None):
    initial = dict(stage="queued", frame=None, files={}, updated=time.time())
    with tempfile.TemporaryDirectory() as directory:
        status_path = Path(directory) / "status.json"
        status_path.write_text(json.dumps(initial), encoding="utf-8")
        spec = dict(spec, folder=folder, state=drive.upload(status_path, folder))
    job = dict(spec=spec, base=base, status=initial, filename=filename,
               output_settings=output_settings, project_id=identity,
               metadata=metadata or {}, created=time.time(), timeout_minutes=timeout)
    phase("Submitting job...")
    reply = api(base + "/run", key, {
        "input": spec, "policy": {"executionTimeout": timeout * 60000, "ttl": 172800000},
    })
    job["id"] = reply["id"]
    add_job(history, job)
    # A cancellation arriving during /run must not leave a newly queued job running.
    if cancel_event.is_set():
        cancel_remote(history, job, key, drive)


def refresh_jobs():
    if busy or not credentials_path().exists():
        return 60
    path = history_path()
    jobs = load_jobs(path)
    configuration = prefs()
    destination = (Path(bpy.path.abspath(configuration.destination))
                   if configuration.auto_download and configuration.destination else None)
    active = [job for job in jobs if job["status"]["stage"] not in TERMINAL or
              (destination and any(frame not in job.get("downloaded", {})
                                   for frame in job["status"].get("files", {})))]
    if not active:
        return 60
    drive, _ = drive_client()
    key = prefs().api_key

    def refresh():
        for job in active:
            state = job["status"]
            remote = None
            status_error = ""
            try:
                state = drive.read_status(job["spec"]["state"])
            except OSError as error:
                status_error = str(error)
            if key and job.get("id"):
                try:
                    remote = api(job["base"] + "/status/" + job["id"], key)
                except OSError as error:
                    status_error = "RunPod status unavailable: " + str(error)
            def change(current):
                # Cancellation may have completed while the polling request was in flight.
                if current["status"]["stage"] in TERMINAL:
                    return
                reconcile(current, state, remote)
                current["status_error"] = status_error
                current["checked_at"] = time.time()
            update_job(path, job["spec"]["state"], change)
            if destination:
                output = destination / job["spec"]["folder"]
                downloaded = dict(job.get("downloaded", {}))
                try:
                    for frame, artifact in state.get("files", {}).items():
                        if frame in downloaded and Path(downloaded[frame]).is_file():
                            continue
                        output.mkdir(parents=True, exist_ok=True)
                        target = output / Path(artifact["name"]).name
                        partial = target.with_suffix(target.suffix + ".part")
                        drive.download(artifact["id"], partial)
                        partial.replace(target)
                        downloaded[frame] = str(target)
                    update_job(path, job["spec"]["state"], lambda current: current.update(downloaded=downloaded))
                except OSError as error:
                    update_job(path, job["spec"]["state"], lambda current:
                               current.update(status_error="Download failed: " + str(error)))

    run(refresh, label="Checking render status...")
    return 60


def poll_jobs():
    try:
        return refresh_jobs()
    except (OSError, ValueError, KeyError) as error:
        global message
        message = "Could not refresh jobs: " + str(error)
        return 60


@persistent
def on_load(_):
    redraw()
    if not busy:
        poll_jobs()


def cancel_remote(path, job, key, drive=None):
    reply = api(job["base"] + "/cancel/" + job["id"], key, {}, method="POST")
    state = None
    if drive and reply.get("status") == "CANCELLED":
        try:
            state = drive.read_status(job["spec"]["state"])
            state.update(stage="cancelled", updated=time.time())
            drive.status_file(job["spec"]["state"], state)
        except OSError:
            pass  # Provider confirmation must still be kept locally if Drive is offline.
    def change(current):
        current["cancel_requested"] = True
        current.pop("cancel_error", None)
        reconcile(current, state or current["status"], reply)
    update_job(path, job["spec"]["state"], change)


class RUNPOD_Cancel(bpy.types.Operator):
    bl_idname = "runpod_render.cancel"
    bl_label = "Cancel process"
    bl_description = "Cancel preparation or request cancellation in RunPod; keep completed frames"
    state_id: StringProperty()

    def execute(self, context):
        global message
        if not self.state_id:
            cancel_event.set()
            message = "Cancelling... Waiting for the current transfer/request to finish."
            return {"FINISHED"}
        path, key = history_path(), prefs().api_key
        try:
            drive, _ = drive_client()
        except (OSError, ValueError, KeyError):
            drive = None
        job = next((job for job in project_jobs() if job["spec"]["state"] == self.state_id), None)
        if not job or job["status"]["stage"] in TERMINAL:
            return {"CANCELLED"}
        update_job(path, self.state_id, lambda current: current.update(cancel_requested=True))
        finished = []
        def cancel():
            try:
                cancel_remote(path, job, key, drive)
            except Exception as error:
                update_job(path, job["spec"]["state"], lambda current:
                           current.update(cancel_requested=False, cancel_error=str(error)))
            finally:
                finished.append(True)
        # Independent from transfers and polling, so cancellation never waits for the UI lock.
        threading.Thread(target=cancel, daemon=True).start()
        def check_finished():
            redraw()
            return None if finished else 0.5
        bpy.app.timers.register(check_finished)
        return {"FINISHED"}


class RUNPOD_Connection(bpy.types.Operator):
    bl_idname = "runpod_render.connection"
    bl_label = "Connection settings"
    action: StringProperty()

    def execute(self, context):
        global connection_status, connection_signature
        if self.action == "preferences":
            bpy.ops.preferences.addon_show(module=__package__)
        elif self.action == "drive":
            webbrowser.open("https://drive.google.com/drive/folders/" + google_info()["folder"])
        elif self.action == "disconnect":
            credentials_path().unlink(missing_ok=True)
            self.report({"INFO"}, "Local connection removed. Worker authorization is unchanged; revoke it in your Google account if needed.")
        elif self.action == "check":
            try:
                base, key = endpoint_settings()
            except ValueError as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            def done(_):
                global connection_status, connection_signature
                connection_status = "RunPod connected"
                connection_signature = (base, key)
            run(lambda: api(base + "/health", key), done, label="Checking RunPod connection...")
        return {"FINISHED"}


def uploaded_scenes(self, context):
    global snapshot_items
    items, seen = [], set()
    for job in project_jobs():
        source = job["spec"]["source"]
        if source not in seen:
            seen.add(source)
            date = time.strftime("%Y-%m-%d %H:%M", time.localtime(job.get("created", job["status"]["updated"])))
            items.append((job["spec"]["state"], f"{job.get('filename', job['spec']['scene'])} - {date}",
                          job.get("output_settings", "Uploaded snapshot")))
    snapshot_items = items or [("NONE", "No uploaded scenes for this file", "")]
    return snapshot_items


class RUNPOD_CacheFolder(bpy.types.PropertyGroup):
    path: StringProperty(name="Cache folder", subtype="DIR_PATH")


class RUNPOD_SceneSettings(bpy.types.PropertyGroup):
    source: EnumProperty(name="Scene source", items=[
        ("CURRENT", "Current Blender file", "Upload the current scene and its caches"),
        ("UPLOADED", "Uploaded scene", "Reuse a saved snapshot; local edits are not included")])
    snapshot: EnumProperty(name="Uploaded scene", items=uploaded_scenes)
    range_mode: EnumProperty(name="Frame range", items=[
        ("SCENE", "Scene range", "Use the scene's frame range"),
        ("CUSTOM", "Custom range", "Render only the requested range")])
    start: IntProperty(name="Start", default=1)
    end: IntProperty(name="End", default=250)
    step: IntProperty(name="Step", default=1, min=1)
    history: BoolProperty(name="Completed jobs", default=False)
    caches: CollectionProperty(type=RUNPOD_CacheFolder)


class RUNPOD_Caches(bpy.types.Operator):
    bl_idname = "runpod_render.cache_folder"
    bl_label = "Cache folder"
    index: IntProperty(default=-1)

    def execute(self, context):
        caches = context.scene.runpod_render.caches
        if self.index < 0:
            caches.add()
        elif self.index < len(caches):
            caches.remove(self.index)
        return {"FINISHED"}


def selected_snapshot(scene):
    return next((job for job in project_jobs() if job["spec"]["state"] == scene.runpod_render.snapshot), None)


def requested_range(scene, mode):
    settings = scene.runpod_render
    if mode == "still":
        return scene.frame_current, scene.frame_current, 1
    if settings.range_mode == "CUSTOM":
        values = settings.start, settings.end, settings.step
    elif settings.source == "UPLOADED":
        job = selected_snapshot(scene)
        if job is None:
            raise ValueError("Select an uploaded scene")
        values = tuple(job.get("metadata", {}).get("scene_range", [job["spec"][key] for key in ("start", "end", "step")]))
    else:
        values = scene.frame_start, scene.frame_end, scene.frame_step
    if values[1] < values[0]:
        raise ValueError("End frame must be at or after start frame")
    return values


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
        f"Frames: {spec['start']}-{spec['end']} (step {spec['step']})",
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
    if "cache_download_and_unpack_seconds" in timing:
        lines.append(f"Cache download and unpack: {timing['cache_download_and_unpack_seconds']:.2f} s")
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


def external_dependencies():
    dependencies = Counter(
        Path(path).resolve() for path in
        bpy.utils.blend_paths(absolute=True, packed=False, local=False)
    )
    bundled_assets = Path(bpy.utils.system_resource("DATAFILES", path="assets")).resolve()
    # Appended data retains its source path for reuse. Subtract each reference
    # individually so a real dependency at the same path can still be detected.
    ignored = Counter()
    for datablock in bpy.data.user_map():
        reference = getattr(datablock, "library_weak_reference", None)
        if reference and reference.filepath:
            ignored[Path(bpy.path.abspath(reference.filepath, library=datablock.library)).resolve()] += 1
    # The worker disables script auto-execution.
    for text in bpy.data.texts:
        if text.filepath:
            ignored[Path(bpy.path.abspath(text.filepath, library=text.library)).resolve()] += 1
    # Ocean stores a default bake path even when it is simulating live.
    for obj in bpy.data.objects:
        for modifier in obj.modifiers:
            if modifier.type == "OCEAN" and not modifier.is_cached and modifier.filepath:
                path = bpy.path.abspath(modifier.filepath, library=obj.library)
                ignored[Path(path).resolve()] += 1
    # The worker renders images with the video sequencer disabled.
    sequencer_sounds = Counter()
    for scene in bpy.data.scenes:
        editor = scene.sequence_editor
        if editor:
            strips = editor.strips_all if hasattr(editor, "strips_all") else editor.sequences_all
            sequencer_sounds.update(
                strip.sound for strip in strips if strip.type == "SOUND" and strip.sound
            )
    for sound, strip_count in sequencer_sounds.items():
        if sound.filepath and sound.users == strip_count:
            path = bpy.path.abspath(sound.filepath, library=sound.library)
            ignored[Path(path).resolve()] += 1
    remaining = set(dependencies - ignored)
    for library in bpy.data.libraries:
        if not library.packed_file:
            remaining.add(Path(bpy.path.abspath(library.filepath, library=library.parent)).resolve())
    return sorted(str(path) for path in remaining if not path.is_relative_to(bundled_assets))


def collect_cache_folders(scene, blend_path):
    folders = {}
    remap = {}
    for owner, prop, library in cache_properties(scene):
        raw = getattr(owner, prop)
        if not raw:
            continue
        path = Path(bpy.path.abspath(raw, library=library)).resolve()
        if not path.is_dir():
            raise ValueError(f"Cache folder not found: {path}")
        if library or owner.is_property_readonly(prop):
            raise ValueError(f"Cache path cannot be remapped in linked data: {path}")
        folders.setdefault(path, f"caches/cache_{len(folders) + 1}")
        remap[raw] = path

    for cache, library in point_caches(scene):
        if not cache.use_disk_cache or cache.use_external:
            continue
        if library:
            raise ValueError("Disk caches on linked data must be made local before rendering")
        name = "blendcache_" + blend_path.stem
        path = blend_path.with_name(name).resolve()
        if not path.is_dir():
            raise ValueError(f"Cache folder not found: {path}")
        # Blender derives this folder from the saved scene basename.
        folders[path] = name
    for entry in scene.runpod_render.caches:
        if not entry.path:
            continue
        path = Path(bpy.path.abspath(entry.path)).resolve()
        if not path.is_dir():
            raise ValueError(f"Cache folder not found: {path}")
        folders.setdefault(path, f"caches/cache_{len(folders) + 1}")
        remap[entry.path] = path
    return folders, {raw: folders[path] for raw, path in remap.items()}


def pack_caches(archive, folders, cancel=None):
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=1) as bundle:
        for directory, name in folders.items():
            count = 0
            for source in sorted(directory.rglob("*")):
                check_cancel(cancel)
                if source.is_symlink():
                    raise ValueError(f"Cache contains a symbolic link: {source}")
                if source.is_file():
                    bundle.write(source, f"{name}/{source.relative_to(directory).as_posix()}")
                    count += 1
            if not count:
                raise ValueError(f"Cache folder is empty: {directory}")


class RUNPOD_Submit(bpy.types.Operator):
    bl_idname = "runpod_render.submit"
    bl_label = "Send render to RunPod"
    mode: StringProperty()

    @classmethod
    def poll(cls, context):
        return not busy

    def execute(self, context):
        scene = context.scene
        try:
            base, key = endpoint_settings()
            drive, parent = drive_client()
            start, end, step = requested_range(scene, self.mode)
        except (OSError, ValueError, KeyError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        identity, timeout = current_project(), prefs().timeout_minutes
        history = history_path()
        if scene.runpod_render.source == "UPLOADED":
            job = selected_snapshot(scene)
            if not job:
                self.report({"ERROR"}, "Select an uploaded scene for this file")
                return {"CANCELLED"}
            spec = dict(job["spec"], start=start, end=end, step=step)
            metadata = job.get("metadata", {})
            if spec.get("cache") and metadata.get("cache_range"):
                low, high = metadata["cache_range"]
                if start < low or end > high:
                    self.report({"ERROR"}, "Requested frames are outside the uploaded cache range")
                    return {"CANCELLED"}
            filename = job.get("filename", spec["scene"])
            def reuse():
                phase("Reusing uploaded scene...")
                folder = drive.unique_folder(filename, parent)
                queue_job(drive, folder, spec, base, key, history, filename,
                          job.get("output_settings", "See uploaded scene"), identity, timeout, metadata)
            run(reuse, label="Preparing uploaded scene...", cancellable=True)
            return {"FINISHED"}
        if not bpy.data.filepath or not scene.camera:
            self.report({"ERROR"}, "Save the scene and set a camera")
            return {"CANCELLED"}
        if scene.render.engine not in ENGINES:
            self.report({"ERROR"}, "Select Cycles or EEVEE")
            return {"CANCELLED"}
        if scene.render.image_settings.file_format not in images:
            self.report({"ERROR"}, "Select a supported image sequence format (video is pending)")
            return {"CANCELLED"}
        blend_path = Path(bpy.data.filepath)
        try:
            folders, remap = collect_cache_folders(scene, blend_path)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        dependencies = [path for path in external_dependencies() if Path(path) not in folders]
        if dependencies:
            self.report({"ERROR"}, "Pack external resources: " + ", ".join(dependencies[:3]))
            return {"CANCELLED"}
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        blend = root / blend_path.name
        bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True, relative_remap=False)
        filename = Path(bpy.data.filepath).stem
        output_settings = (
            f"{ENGINES[scene.render.engine]} | {scene.render.resolution_x} x {scene.render.resolution_y} | "
            f"{scene.render.resolution_percentage}% | {scene.render.image_settings.file_format} | "
            f"{scene.render.fps / scene.render.fps_base:g} fps"
        )
        name = scene.name
        spec = dict(scene=name, start=start, end=end, step=step)
        metadata = dict(blender_version=bpy.app.version_string,
                        scene_range=[scene.frame_start, scene.frame_end, scene.frame_step],
                        cache_folders=len(folders))
        ranges = [(cache.frame_start, cache.frame_end) for cache, _ in point_caches(scene)
                  if cache.is_baked and (cache.use_disk_cache or cache.use_external)]
        if ranges:
            metadata["cache_range"] = [max(item[0] for item in ranges), min(item[1] for item in ranges)]

        def submit():
            try:
                if folders:
                    phase("Packing caches...")
                    archive = root / "render-caches.zip"
                    pack_caches(archive, folders, cancel_event)
                phase("Uploading scene...")
                folder = drive.unique_folder(filename, parent)
                spec["source"] = drive.upload(blend, folder, cancel=cancel_event)
                if folders:
                    phase("Uploading caches...")
                    spec.update(cache=drive.upload(archive, folder, cancel=cancel_event), cache_paths=remap,
                                source_name=blend.name)
                queue_job(drive, folder, spec, base, key, history, filename, output_settings,
                          identity, timeout, metadata)
            finally:
                temporary.cleanup()

        def done(_):
            global message
            message = "Cancellation requested." if cancel_event.is_set() else "Submitted. You can close Blender."

        run(submit, done, label="Preparing scene...", cancellable=True)
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
        if action == "assign":
            if not current_project():
                self.report({"ERROR"}, "Save this Blender file first")
                return {"CANCELLED"}
            update_job(path, self.state_id, lambda item: item.update(project_id=current_project()))
            return {"FINISHED"}
        if job.get("project_id") != current_project():
            self.report({"ERROR"}, "This job belongs to a different Blender file")
            return {"CANCELLED"}
        if action == "open_drive":
            webbrowser.open("https://drive.google.com/drive/folders/" + job["spec"]["folder"])
            return {"FINISHED"}
        destination = prefs().destination
        if action in {"open", "download", "compositor", "report"} and not destination:
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
        identity, timeout = current_project(), prefs().timeout_minutes

        def perform():
            if action in {"reuse", "rerender"}:
                spec = dict(job["spec"])
                if action == "reuse":
                    spec.update(frame_range)
                filename = job.get("filename", spec["scene"])
                folder = drive.unique_folder(filename, parent)
                queue_job(drive, folder, spec, job["base"], key, path, filename,
                          job.get("output_settings", "See uploaded scene"), identity, timeout,
                          job.get("metadata", {}))
                return []
            if action == "retry":
                reply = api(job["base"] + "/run", key, {
                    "input": job["spec"], "policy": {"executionTimeout": timeout * 60000, "ttl": 172800000},
                })
                job["id"] = reply["id"]
                job.pop("runpod", None)
                job.pop("cancel_requested", None)
                job["status"].update(stage="queued", updated=time.time(), error="")
                save_jobs(path, jobs)
                if cancel_event.is_set():
                    cancel_remote(path, job, key, drive)
                return []
            folder = output / job["spec"]["folder"]
            folder.mkdir(parents=True, exist_ok=True)
            status = drive.read_status(job["spec"]["state"])
            paths = []
            for _, artifact in sorted(status["files"].items(), key=lambda item: int(item[0])):
                phase("Downloading results...")
                target = folder / Path(artifact["name"]).name
                partial = target.with_suffix(target.suffix + ".part")
                drive.download(artifact["id"], partial)
                partial.replace(target)
                paths.append(target)
            return paths

        def done(paths):
            if action == "compositor" and paths:
                # File loads may invalidate Blender data held while the transfer ran.
                if current_project() == identity:
                    import_compositor(bpy.context.scene, paths)
            elif action == "open" and paths:
                open_default(paths[0])

        run(perform, done, cancellable=True)
        return {"FINISHED"}


class RUNPOD_CheckScene(bpy.types.Operator):
    bl_idname = "runpod_render.check_scene"
    bl_label = "Check scene"
    bl_description = "Check render settings, external files and cache folders without using a GPU"

    def execute(self, context):
        scene = context.scene
        try:
            if scene.runpod_render.source == "UPLOADED":
                if selected_snapshot(scene) is None:
                    raise ValueError("Select an uploaded scene")
                requested_range(scene, "animation")
                self.report({"INFO"}, "Uploaded snapshot selected. Local edits are not included.")
                return {"FINISHED"}
            if not bpy.data.filepath or not scene.camera:
                raise ValueError("Save the scene and set a camera")
            if scene.render.engine not in ENGINES:
                raise ValueError("Select Cycles or EEVEE")
            if scene.render.image_settings.file_format not in images:
                raise ValueError("Select a supported image sequence format")
            folders, _ = collect_cache_folders(scene, Path(bpy.data.filepath))
            missing = [path for path in external_dependencies() if Path(path) not in folders]
            if missing:
                raise ValueError("Pack external resources: " + ", ".join(missing[:3]))
            requested_range(scene, "animation")
            self.report({"INFO"}, f"Scene checks passed. {len(folders)} cache folders will be uploaded.")
        except (OSError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


def draw_job(layout, job):
    spec, state = job["spec"], job["status"]
    box = layout.box()
    box.label(text=job.get("filename", spec["scene"]), icon="FILE_BLEND")
    stage = state["stage"]
    labels = {"queued": "Queued", "preparing": "Preparing worker",
              "rendering": "Rendering", "uploading": "Uploading results",
              "saved": "Frame saved", "completed": "Completed", "failed": "Failed",
              "cancelled": "Cancelled", "timed_out": "Time limit reached"}
    label = "Cancelling..." if job.get("cancel_requested") else labels.get(stage, stage)
    if state.get("frame") is not None and stage not in TERMINAL:
        label += f" | Frame {state['frame']}"
    box.label(text=label)
    done, total = progress(job)
    box.progress(factor=done / total if total else 0, type="BAR",
                 text=f"{done}/{total} frames completed")
    box.label(text=f"Frames {spec['start']}-{spec['end']} | Step {spec['step']}")
    box.label(text=time.strftime("Updated %H:%M:%S", time.localtime(state["updated"])))
    error = job.get("cancel_error") or state.get("error") or job.get("status_error")
    if error:
        box.label(text=str(error)[-100:], icon="ERROR")
    if stage not in TERMINAL:
        # Cancellation stays enabled even while another upload or polling request runs.
        row = box.row()
        row.enabled = not job.get("cancel_requested")
        row.operator("runpod_render.cancel", icon="CANCEL").state_id = spec["state"]
    options = [("open_drive", "Open Drive"), ("report", "Download report")]
    if state.get("files"):
        options.extend([("download", "Download results"), ("open", "Open result"),
                        ("compositor", "Import into Compositor")])
    if stage in {"failed", "cancelled", "timed_out"} and done < total:
        options.append(("retry", "Retry missing frames"))
    for action, label in options:
        row = box.row()
        row.enabled = not busy
        operator = row.operator("runpod_render.jobs", text=label)
        operator.action, operator.state_id = action, spec["state"]


class RUNPOD_PT_Render(bpy.types.Panel):
    bl_label = "RunPod Render"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        layout, scene, settings = self.layout, context.scene, prefs()
        options = scene.runpod_render
        connected = bool(google_info())
        configured = bool(settings.endpoint and settings.api_key)
        verified = connection_signature == (BASE + settings.endpoint.strip(), settings.api_key)
        layout.label(text="RunPod connected" if verified else
                     ("RunPod configured" if configured else "RunPod not configured"),
                     icon="CHECKMARK" if configured else "ERROR")
        layout.label(text="Google Drive connected" if connected else "Google Drive not connected",
                     icon="CHECKMARK" if connected else "ERROR")
        layout.operator("runpod_render.connection", text="Open add-on preferences",
                        icon="PREFERENCES").action = "preferences"
        box = layout.box()
        box.label(text="Scene & assets")
        controls = box.column()
        controls.enabled = not busy
        controls.prop(options, "source", text="")
        snapshot = None
        if options.source == "UPLOADED":
            controls.prop(options, "snapshot", text="")
            snapshot = selected_snapshot(scene)
            box.label(text="Uses the uploaded snapshot.")
            box.label(text="Local changes are not included.")
            if snapshot:
                info = snapshot.get("metadata", {})
                box.label(text=f"Caches: {info.get('cache_folders', 'Unknown')}")
                box.label(text=f"Saved with Blender {info.get('blender_version', 'unknown')}")
        else:
            controls.label(text="Detected simulation cache folders are included automatically.")
            for index, item in enumerate(options.caches):
                row = controls.row(align=True)
                row.prop(item, "path", text="")
                row.operator("runpod_render.cache_folder", text="", icon="X").index = index
            controls.operator("runpod_render.cache_folder", text="Add cache folder", icon="ADD")
        controls.operator("runpod_render.check_scene", icon="CHECKMARK")
        box = layout.box()
        box.label(text="Render settings")
        if options.source == "UPLOADED":
            if snapshot:
                for part in snapshot.get("output_settings", "See uploaded scene").split(" | "):
                    box.label(text=part)
        else:
            box.label(text=ENGINES.get(scene.render.engine, "Unsupported render engine"))
            box.label(text=f"{scene.render.resolution_x} x {scene.render.resolution_y} | "
                           f"{scene.render.resolution_percentage}% | {scene.render.image_settings.file_format}")
            box.label(text=f"FPS {scene.render.fps / scene.render.fps_base:g}")
        controls = box.column()
        controls.enabled = not busy
        controls.prop(options, "range_mode", text="")
        if options.range_mode == "CUSTOM":
            row = controls.row(align=True)
            row.prop(options, "start")
            row.prop(options, "end")
            controls.prop(options, "step")
        try:
            start, end, step = requested_range(scene, "animation")
            box.label(text=f"Frames {start}-{end} | Step {step} | {len(range(start, end + 1, step))} frames")
        except ValueError as error:
            box.label(text=str(error), icon="ERROR")
        box.label(text=f"Current frame: {scene.frame_current}")
        if settings.worker_description:
            box.label(text=settings.worker_description)
        else:
            box.label(text="Serverless | Existing worker configuration")
        actions = layout.column(align=True)
        actions.enabled = not busy and connected and configured and bool(bpy.data.filepath)
        actions.scale_y = 1.3
        actions.operator("runpod_render.submit", text="Render current frame",
                         icon="RENDER_STILL", depress=True).mode = "still"
        actions.operator("runpod_render.submit", text="Render animation",
                         icon="RENDER_ANIMATION", depress=True).mode = "animation"
        if not bpy.data.filepath:
            layout.label(text="Save your Blender file to render and track its jobs.", icon="INFO")
        if message and operation_project == current_project():
            layout.label(text=message[:110])
            if busy and operation_cancellable:
                layout.operator("runpod_render.cancel", icon="CANCEL")
        jobs = project_jobs()
        layout.label(text="Jobs for this Blender file")
        active = [job for job in jobs if job["status"]["stage"] not in TERMINAL]
        completed = [job for job in jobs if job["status"]["stage"] in TERMINAL]
        for job in active:
            draw_job(layout, job)
        if not jobs:
            layout.label(text="No jobs submitted for this file yet.")
        if completed:
            draw_job(layout, completed[0])
            if len(completed) > 1:
                layout.prop(options, "history", text=f"Older jobs ({len(completed) - 1})",
                            icon="TRIA_DOWN" if options.history else "TRIA_RIGHT", emboss=False)
                if options.history:
                    for job in completed[1:]:
                        draw_job(layout, job)


classes = (RUNPOD_Preferences, RUNPOD_CacheFolder, RUNPOD_SceneSettings,
           RUNPOD_Connection, RUNPOD_SetupWorker, RUNPOD_Cancel, RUNPOD_Caches, RUNPOD_CheckScene,
           RUNPOD_Connect, RUNPOD_WorkerSettings, RUNPOD_Submit, RUNPOD_Jobs, RUNPOD_PT_Render)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.runpod_render = PointerProperty(type=RUNPOD_SceneSettings)
    bpy.app.handlers.load_post.append(on_load)
    bpy.app.timers.register(poll_jobs, first_interval=1, persistent=True)


def unregister():
    cancel_event.set()
    if on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load)
    if hasattr(bpy.types.Scene, "runpod_render"):
        del bpy.types.Scene.runpod_render
    if bpy.app.timers.is_registered(poll_jobs):
        bpy.app.timers.unregister(poll_jobs)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
