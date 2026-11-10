"""Explicit Serverless provisioning using RunPod's REST v2 contract."""
from .transport import api

CONTROL = "https://api.runpod.io/v2"
IMAGE = "ghcr.io/tonydark0/easy-runpod-for-blender-render/worker:blender-4.5.4"


def gpu_selection(catalog, pool):
    candidates = [gpu for gpu in catalog["gpus"] if gpu.get("pool") == pool]
    eligible = [gpu for gpu in candidates if "MIG" not in gpu["id"].upper()]
    if pool == "ADA_24":
        eligible = [gpu for gpu in eligible if "4090" in gpu["id"]]
    if not eligible:
        raise ValueError("The selected GPU profile is not available in the RunPod catalog")
    prices = [gpu.get("price", {}).get("serverless") for gpu in eligible]
    if not all(isinstance(price, (int, float)) and price > 0 for price in prices):
        raise ValueError("RunPod did not return a Serverless price; review pricing in the console")
    return ({"pools": [pool], "count": 1, "minCudaVersion": "12.8",
             "excludedTypes": [gpu["id"] for gpu in candidates if gpu not in eligible]},
            max(prices), ", ".join(gpu["name"] for gpu in eligible))


def endpoint_payload(name, gpu, credentials, timeout, disk):
    return dict(name=name, type="QUEUE", image=IMAGE, disk=disk,
                gpu=gpu, scaling={"type": "QUEUE_DELAY", "queueDelay": 4},
                workers={"min": 0, "max": 1, "idleTimeout": 5},
                flashboot="FLASHBOOT", timeout=timeout * 60000,
                env={"DRIVE_CLIENT_ID": credentials["client_id"],
                     "DRIVE_CLIENT_SECRET": credentials["client_secret"],
                     "DRIVE_REFRESH_TOKEN": credentials["refresh_token"]})


def provision(key, payload, endpoint=""):
    if endpoint:
        health = api("https://api.runpod.ai/v2/" + endpoint + "/health", key)
        jobs = health.get("jobs", {})
        if jobs.get("inProgress", 0) or jobs.get("inQueue", 0):
            raise ValueError("Wait for this endpoint's jobs to finish before updating the worker")
        update = {name: value for name, value in payload.items() if name != "type"}
        return api(CONTROL + "/serverless/" + endpoint, key, update, method="PATCH")
    # Do not automatically retry a creation request: its response could be lost after success.
    return api(CONTROL + "/serverless", key, payload)
