import json
import sys
import time
from pathlib import Path

import bpy

from cache_paths import cache_properties

scene_name, frame, output, *arguments = sys.argv[sys.argv.index("--") + 1:]
scene = bpy.data.scenes[scene_name]
if arguments:
    mapping = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    for owner, prop, _ in cache_properties(scene):
        raw = getattr(owner, prop)
        if raw in mapping:
            setattr(owner, prop, mapping[raw])
scene.render.use_compositing = False
scene.render.use_sequencer = False
if scene.render.engine == "CYCLES":
    scene.cycles.device = "GPU"
    cycles = bpy.context.preferences.addons["cycles"].preferences
    cycles.compute_device_type = "OPTIX"
    cycles.refresh_devices()
    devices = [device for device in cycles.devices if device.type == "OPTIX"]
    if not devices:
        raise RuntimeError("No OptiX GPU available")
    for device in cycles.devices:
        device.use = device in devices
elif scene.render.engine not in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
    raise RuntimeError(f"Unsupported render engine: {scene.render.engine}")
scene.frame_set(int(frame))
scene.render.filepath = output
scene.render.use_file_extension = True
started = time.perf_counter()
bpy.ops.render.render(write_still=True, scene=scene.name)
Path(output + '.timing').write_text(str(time.perf_counter() - started), encoding='ascii')
