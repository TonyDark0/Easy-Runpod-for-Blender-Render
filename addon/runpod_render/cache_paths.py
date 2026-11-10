def point_caches(scene):
    if scene.rigidbody_world:
        yield scene.rigidbody_world.point_cache, scene.library
    for obj in scene.objects:
        for particles in obj.particle_systems:
            yield particles.point_cache, obj.library
        for modifier in obj.modifiers:
            if modifier.type in {"CLOTH", "SOFT_BODY"}:
                yield modifier.point_cache, obj.library
            elif modifier.type == "DYNAMIC_PAINT" and modifier.canvas_settings:
                for surface in modifier.canvas_settings.canvas_surfaces:
                    yield surface.point_cache, obj.library


def cache_properties(scene):
    for cache, library in point_caches(scene):
        if cache.use_external and cache.filepath:
            yield cache, "filepath", library
    for obj in scene.objects:
        for modifier in obj.modifiers:
            if modifier.type == "OCEAN" and modifier.is_cached:
                yield modifier, "filepath", obj.library
            elif modifier.type == "FLUID" and modifier.domain_settings:
                domain = modifier.domain_settings
                if domain.has_cache_baked_any:
                    yield domain, "cache_directory", obj.library
