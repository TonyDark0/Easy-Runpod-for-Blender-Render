# Easy RunPod for Blender Render

A cost-conscious alternative to traditional render farms. Render Cycles stills and image-sequence animations on your own RunPod Serverless endpoint, save results to your Google Drive, and track progress inside Blender.

**Early development release.** Real Cycles renders, animation ranges, scene reuse and cache transfers have been exercised. The new automated endpoint setup has local tests but still needs a complete live onboarding test. Public Google sign-in is not yet published; current development builds use a Desktop OAuth JSON. This project is independent of Blender, Google and RunPod.

## Get started

1. Install the add-on ZIP in Blender **Preferences → Add-ons → Install from Disk**, then enable it.
2. Open its preferences, connect Google Drive and configure your RunPod endpoint.
3. Save your `.blend`, pack supported external assets, and include baked simulation caches.
4. In **Render Properties → RunPod Render**, check your scene and choose **Render current frame** or **Render animation**.
5. Wait for successful submission before closing Blender. The worker renders and uploads results without your computer staying on.

See the [setup and usage guide](docs/usage.md) for the current Google testing setup and the distinction between a new managed worker and an existing endpoint. To build a ZIP from source, see [technical documentation](docs/technical.md). Packages can be found under [Releases](https://github.com/TonyDark0/Easy-Runpod-for-Blender-Render/releases) when published; a release asset is not guaranteed to exist for every commit.

## Why use it?

- Keep working locally while another GPU renders.
- Pay RunPod directly through your own account; the add-on adds no rendering service fee.
- Store scene snapshots, caches, rendered frames and status in your own Drive.
- Reuse an uploaded snapshot to render another range without uploading the scene again.
- Track jobs for the current `.blend`, with a completed-frame progress bar and cancellation.
- Download results and reports, open images, or bring downloaded images into the compositor.
- Inspect and modify the open-source add-on and worker under GPL-3.0-or-later.

Lower cost is a goal, not a guarantee. Your scene, GPU, transfer time and failure rate determine the result. A fast local GPU can be quicker for individual frames; managed farms may offer more parallel capacity and production support. See [benchmarks and pricing comparisons](docs/benchmarks.md).

## Support development

[Create a RunPod account using my affiliate link](https://runpod.io?ref=ingivjcz).

**Affiliate disclosure:** This is the project maintainer's affiliate link. I may receive referral compensation when you sign up or use RunPod through it, which helps support development of this add-on. Using it is optional. You can also visit [RunPod without the referral link](https://www.runpod.io/). Affiliate participation does not change the benchmark measurements or imply that RunPod is always the cheapest option.

## Documentation

| Page | Contents |
| --- | --- |
| [Setup and usage](docs/usage.md) | Installation, accounts, worker setup, stills, animations, caches and troubleshooting |
| [Benchmarks and costs](docs/benchmarks.md) | Junk Shop and Panthera Spelaea measurements, limitations and sourced farm pricing |
| [Technical documentation](docs/technical.md) | Architecture, job state, authentication, packaging and tests |
| [Limitations and roadmap](docs/roadmap.md) | Current boundaries and possible future releases |
| [Privacy policy](docs/privacy.md) | Data processed, credentials, providers, retention and deletion |
| [Google publication checklist](docs/google-publishing.md) | Public contact, OAuth configuration and remaining release steps |

## Compatibility and current boundaries

Blender 4.5+ is the declared minimum. Registration and panel smoke tests have passed on Windows with Blender 4.5.10 and 5.2.0. The supplied worker image uses **Blender 4.5.4**; newer `.blend` features may not render correctly in that worker. EEVEE has a code path but needs broader headless GPU validation before being considered production-ready.

The current worker disables **compositing, the video sequencer and automatic script execution**. It supports PNG, JPEG, TIFF, OpenEXR and multilayer OpenEXR outputs, not encoded video. Third-party rendering dependencies are not installed automatically. Use baked caches and test representative frames before committing a production job.

The managed setup configures **0 active workers, 1 maximum worker and 1 GPU per worker**. Multi-worker frame distribution and dedicated Pods are outside the first public release. Failed work can still incur RunPod charges; execution limits and no automatic render retries help contain consumption.

## Contact

- Project and source: [TonyDark0/Easy-Runpod-for-Blender-Render](https://github.com/TonyDark0/Easy-Runpod-for-Blender-Render)
- Bugs and feature requests: [GitHub Issues](https://github.com/TonyDark0/Easy-Runpod-for-Blender-Render/issues)
- Support and privacy: [theborderculture@gmail.com](mailto:theborderculture@gmail.com)

Do not post API keys, OAuth JSON, refresh tokens, private scene files or unredacted logs in public issues. This is a community project, without a production support SLA.
