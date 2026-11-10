# Technical documentation

## Components

| Location | Responsibility |
| --- | --- |
| `addon/runpod_render/__init__.py` | Blender preferences, scene controls, operators, background operations and periodic polling |
| `jobs.py` | Local job history, full-path project identity, progress and provider-state reconciliation |
| `oauth.py` / `credentials.py` | Desktop browser OAuth with PKCE/state, loopback callback and local credential storage |
| `transport.py` | RunPod requests and Google Drive uploads/downloads |
| `setup.py` | Catalog/pricing lookup and explicit managed Serverless provisioning through REST v2 |
| `cache_paths.py` | Supported simulation-cache discovery |
| `worker/handler.py` | Scene/cache download, sequential frame processing, uploads and status updates |
| `worker/render.py` | Blender background process, GPU selection, path remapping and render output |
| `worker/Dockerfile` | CUDA 12.8.1 runtime, Blender 4.5.4 and RunPod SDK 1.7.13 |

## Request lifecycle

The add-on saves a temporary copy of the current `.blend` and optionally packs cache directories into a ZIP. It creates a unique Drive output folder, uploads the source and an initial `status.json`, then submits `/run` to `https://api.runpod.ai/v2/{endpoint}`.

The input contains Drive IDs (`source`, `folder`, `state`), scene name, inclusive `start`/`end`, and `step`. Cache jobs also include the cache archive ID, source basename and path mapping. Google refresh tokens and the RunPod API key are **not** included in this job input. The request carries an execution timeout and a 48-hour TTL; the UI currently permits at most 24 hours of execution per job.

The worker reads Drive credentials from its environment, downloads the scene and cache archive once per job, validates archive paths and renders frames sequentially. Each frame starts a separate Blender process. Cycles selects an available OptiX device; EEVEE uses its headless rendering path. Compositing, sequencer evaluation and automatic Python execution are disabled.

After an image upload succeeds, its Drive ID and timings are recorded in `status.json`. Retrying the same job specification preserves that map and skips recorded frames. A new request that reuses a source snapshot creates a separate output/status folder but references the same source and cache IDs.

## State and cancellation

Typical worker stages are `queued`, `preparing`, `rendering`, `uploading`, `saved`, and `completed`; errors produce `failed`. Provider responses can produce `cancelled` or `timed_out`. The progress numerator counts requested frame numbers in the uploaded-files map, not the current render frame index.

The UI refreshes approximately every 60 seconds. Local history survives reopening Blender on the same computer. It is not embedded as a transferable remote history index inside the `.blend`. The file identity is a SHA-256 hash of the normalized absolute path; it is **not** a content fingerprint or an embedded UUID. Save As, renaming and moving files change the identity.

Local cancellation uses an event checked between preparation and upload chunks. Remote cancellation runs independently of the normal UI operation lock, calls `/cancel/{id}` and records provider confirmation. If possible, it also stores the confirmed cancellation in Drive. Local job updates use a thread lock and atomic file replacement; this is not a cross-process database lock for multiple simultaneous Blender instances.

## Credentials and network boundaries

The RunPod API key is stored in Blender add-on preferences and masked in the UI; masking is not encryption. The Google authorization file is stored separately in Blender's configuration directory. New Windows credential writes use the user's DPAPI protection. Other systems use a local file created with restrictive permissions; legacy plaintext Windows credentials remain readable until reconnection rewrites them.

OAuth uses a random local loopback port, state validation, PKCE S256, offline access and `drive.file`. The add-on reads basic Drive account metadata to identify the connected account. A project-owned Desktop OAuth client can be included at packaging time; user refresh tokens must never be bundled.

Managed setup sends the Google client ID, desktop client secret and refresh token to the user's RunPod endpoint environment. The RunPod management key is not forwarded to the worker. The manual clipboard helper is retained in Advanced for existing endpoints. Local disconnect removes only the local connection, not the remote worker authorization.

No central rendering backend or maintainer-operated token broker is part of this implementation. See the [privacy policy](privacy.md) for the complete data flow and revocation instructions.

## Build and test

From the repository root, with Python 3.11+:

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python tools/build_addon.py --output dist
blender --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py
blender --command extension validate dist/runpod_render-0.2.1.zip
```

For a public package, after configuring the project's OAuth client:

```sh
python tools/build_addon.py --output dist --google-client /path/to/project-desktop-client.json
```

This packages only the Desktop client ID and secret fields. It does not publish the Google app or verify its brand. Do not use an unrelated personal project's OAuth client for a public build.

Build the worker with:

```sh
docker build -f worker/Dockerfile -t easy-runpod-blender-worker .
```

GitHub Actions checks Python/tests/package creation and separately builds the worker image when relevant paths change. The worker image currently uses the mutable `blender-4.5.4` tag. Immutable image pinning, migration and rollout controls are planned; a successful image build is not evidence that every existing endpoint was redeployed.

## Validation scope

The test suite covers project isolation, progress, cancellation reconciliation, concurrent local updates, chunked upload cancellation, managed setup payloads and credential storage. Blender smoke tests validate registration, settings and panel code on 4.5.10 and 5.2.0. These do not replace live Google onboarding, endpoint provisioning, GPU cancellation or cross-platform rendering tests.

Reports currently use the fixed USD 0.75/hour reference even when setup quotes another rate. They are not invoices. GPU identity is not retained by the normal historical render handler; benchmark improvements are listed in the [roadmap](roadmap.md).
