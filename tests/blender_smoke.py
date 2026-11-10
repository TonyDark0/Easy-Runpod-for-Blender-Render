"""Run with Blender --background --factory-startup --python-exit-code 1 --python ..."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import runpod_render as addon

addon.register()
entry = bpy.context.preferences.addons.new()
entry.module = "runpod_render"
scene = bpy.context.scene
assert scene.runpod_render.source == "CURRENT"
scene.runpod_render.range_mode = "CUSTOM"
scene.runpod_render.start = 21
scene.runpod_render.end = 30
assert addon.requested_range(scene, "animation") == (21, 30, 1)
assert addon.requested_range(scene, "still") == (scene.frame_current, scene.frame_current, 1)
scene.runpod_render.end = 1
try:
    addon.requested_range(scene, "animation")
    raise AssertionError("Invalid range accepted")
except ValueError:
    pass
scene.runpod_render.end = 30


class Layout:
    def __init__(self):
        self.labels = []
        self.properties = []
        self.progress_values = []

    def column(self, **kwargs): return self
    def row(self, **kwargs): return self
    def box(self): return self
    def label(self, *, text, **kwargs): self.labels.append(text)
    def prop(self, owner, name, **kwargs):
        getattr(owner, name)
        self.properties.append(name)
    def operator(self, name, **kwargs):
        module, operation = name.split(".")
        getattr(getattr(bpy.ops, module), operation).get_rna_type()
        return SimpleNamespace()
    def progress(self, **kwargs): self.progress_values.append(kwargs)


with tempfile.TemporaryDirectory() as directory:
    addon.history_path = lambda: Path(directory) / "jobs.json"
    addon.credentials_path = lambda: Path(directory) / "credentials.json"
    addon.current_project = lambda: "project-a"
    current = dict(project_id="project-a", filename="Scene", created=1,
                   spec=dict(scene="Scene", source="file", state="state", folder="folder", start=1, end=11, step=1),
                   status=dict(stage="rendering", frame=2, files={"1": {}}, updated=1))
    addon.save_jobs(addon.history_path(), [current])
    layout = Layout()
    addon.RUNPOD_PT_Render.draw(SimpleNamespace(layout=layout), bpy.context)
    assert layout.progress_values[0]["text"] == "1/11 frames completed"
    assert "endpoint" not in layout.properties
    assert "api_key" not in layout.properties
    assert "oauth_file" not in layout.properties
    settings = addon.prefs()
    settings.advanced = True
    addon.RUNPOD_Preferences.draw(SimpleNamespace(layout=Layout(), **{
        name: getattr(settings, name) for name in
        ("api_key", "endpoint", "oauth_file", "destination", "auto_download", "drive_folder_name", "advanced",
         "show_legacy", "timeout_minutes", "gpu_profile", "disk_gb", "managed_endpoint", "worker_description")
    }), bpy.context)
    scene.runpod_render.source = "UPLOADED"
    scene.runpod_render.snapshot = "state"
    assert addon.selected_snapshot(scene)["spec"]["source"] == "file"
    addon.RUNPOD_PT_Render.draw(SimpleNamespace(layout=Layout()), bpy.context)

addon.unregister()
assert not hasattr(bpy.types.Scene, "runpod_render")
print("BLENDER_SMOKE_OK")
