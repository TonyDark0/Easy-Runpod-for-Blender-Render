# Limitations and possible improvements

This page distinguishes current behavior from proposed work. Roadmap items are not release promises.

## Current limitations

- Development release: public Google OAuth onboarding and a live test of automated worker provisioning remain pending.
- One worker per managed endpoint. Dedicated Pods, multi-worker frame distribution, editable production queues and automatic job splitting are not implemented.
- Blender UI compatibility does not imply remote scene compatibility. The current worker is Blender 4.5.4, including when the local file was saved by a newer Blender.
- Cycles has real render evidence. EEVEE needs broader testing across headless GPU environments and scenes.
- Compositing, the video sequencer and automatic script execution are disabled remotely. Third-party render engines and add-ons are not automatically installed.
- Still images and image-sequence output only; no video encoding, audio output or full compositor File Output delivery.
- Simulations must be prepared for remote evaluation. Only supported cache paths are remapped, folders are bundled in full, and preflight is not a universal dependency validator.
- Each frame launches a new Blender process. Reusing a snapshot saves the desktop upload but not the worker's download or per-frame scene loading.
- Progress is based on uploaded frames, not samples or tiles. Polling is approximately every 60 seconds while Blender is open.
- History is local and keyed by full file path. File moves, renames, Save As, another computer or concurrent Blender processes require care.
- The report's USD 0.75/hour cost is a reference estimate. Actual startup, idle, storage, retry and tax costs are not fully attributed.
- Cancellation is a request, not an instantaneous refund or guaranteed zero-cost operation. A hung render can consume until its configured execution limit.
- Google Testing authorizations expire; local disconnect does not revoke remote credentials. Non-Windows secure-store integration is pending.
- Scene upload deduplication by content hash, quota planning, automatic endpoint recovery after ambiguous failures and automatic compositor sequence assembly are not implemented.
- Capacity, network and provider outages can delay or interrupt a render. No production SLA is supplied by this project.

## Before a public release

1. Validate new-user provisioning and reconnection against live RunPod and Google accounts.
2. Publish the Google OAuth app with accurate contact, privacy and approved branding where required.
3. Exercise cancellation during preparation, upload, queueing and active GPU rendering with billing observations.
4. Record GPU model, image digest, Blender version and actual rates in reports.
5. Validate EEVEE, supported caches and recovery across representative scenes and operating systems.
6. Improve credential storage, managed setup recovery and immutable worker version selection.

## Later releases

- Divide animation ranges into independent blocks across multiple Serverless workers, with explicit concurrency and spend-rate controls.
- Persistent Blender processes where safe, frame checkpoints and automatic range splitting within execution limits.
- Snapshot content hashes, cache manifests, incremental transfers and storage estimates.
- Portable project identifiers and remote history recovery.
- Automatic compositor image-sequence import, previews and richer reports.
- More worker Blender versions with explicit local/remote compatibility checks.
- Measured comparisons against managed render farms using identical scene/settings and billed invoices.

Dedicated Pods remain outside the first public release and are not required for the planned Serverless parallel-rendering work.
