import sys

import bpy

scene_name, frame, output = sys.argv[sys.argv.index("--") + 1:]
scene = bpy.data.scenes[scene_name]
scene.render.engine = "CYCLES"
scene.render.use_compositing = False
scene.render.use_sequencer = False
scene.cycles.device = "GPU"
cycles = bpy.context.preferences.addons["cycles"].preferences
cycles.compute_device_type = "OPTIX"
cycles.refresh_devices()
devices = [device for device in cycles.devices if device.type == "OPTIX"]
if not devices:
    raise RuntimeError("No OptiX GPU available")
for device in cycles.devices:
    device.use = device in devices
scene.frame_set(int(frame))
scene.render.filepath = output
scene.render.use_file_extension = True
bpy.ops.render.render(write_still=True, scene=scene.name)
