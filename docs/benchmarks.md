# Render measurements and cost comparisons

Published 2026-11-10. These are development measurements made on 2026-11-09, not Blender Open Data submissions or a controlled GPU ranking. The source scenes are [Blender demo files](https://www.blender.org/download/demo-files/): **The Junk Shop**, by Alex Treviño, original concept by Anaïs Maamar; and **Panthera Spelaea**, the Blender 5.2 splash by Joanna Kobierska (see its original README for full credits). Download scenes from Blender and follow their individual licenses; no scene assets are redistributed here.

## Hardware and evidence

Local machine: **NVIDIA GeForce RTX 4070 Laptop GPU, 8 GB VRAM**, Intel Core i9-13980HX and 16 GB RAM, as shown in the maintainer's system screenshot. Local render times come from Blender Render Result screenshots.

Cloud: the development endpoint was configured for the **24 GB availability pool**, not a single guaranteed GPU model. The historical reports say **GPU: Unavailable** and the supplied worker logs do not identify the card. **We cannot attribute these results to an RTX 3090, L4, RTX A5000 or RTX 4090.** Pool membership and VRAM are not a measurement of performance. GPU identity must be recorded in a future benchmark run.

The supplied worker image targets Blender 4.5.4; the local UI was Blender 5.2. Exact loaded image digests, sampling settings, Blender runtime versions and scene hashes were not retained for every run. The maintainer reported matching settings, but these records are not sufficient to establish a fully controlled comparison across Blender versions.

Numbers below were transcribed from the local job history, exported report and provided screenshots. Only timing data is published; account identifiers, Drive IDs, job IDs and private file paths are omitted. Machine-readable values are in [measurements.json](../benchmarks/measurements.json).

## Observed times

| Scene / request | Output | Frames | Local Render Result | Cloud render + save | Worker execution | Estimated worker cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Junk Shop, still | 2000 × 1000, 100%, TIFF | 1 | 57.87 s | 50.91 s | 73.06 s | USD 0.01522 |
| Junk Shop, short range | 2000 × 1000, 100%, TIFF | 1–3 | Not measured as a local batch | 100.75 s total / 33.58 s mean | 132.06 s total | USD 0.02751 total / 0.00917 per frame |
| Panthera Spelaea, still | 1000 × 500, 100%, PNG | 0 | 69.60 s | 112.63 s | 130.81 s | USD 0.02725 |

All cloud costs in this table use **USD 0.75/hour as a reference**, not verified billed charges. Junk Shop worker durations come from handler timing; Panthera uses the provider's executionTime. The measurements are not perfectly identical timer boundaries. Render + save is a subset of worker execution, so **do not add them together**. Local Blender's displayed time also does not necessarily cover the same operations as the worker's render + save timer.

The Junk Shop still's cloud render + save interval was about **1.14× faster** than the local displayed time, but its full worker interval was longer. Panthera's cloud render + save interval took about **1.62× as long** as the local displayed time. These tests do not support a blanket claim that cloud rendering is faster.

### Junk Shop per-frame detail

| Frame | Render + save | Blender process | Result upload |
| --- | ---: | ---: | ---: |
| 1 | 49.51 s | 51.40 s | 2.36 s |
| 2 | 30.82 s | 32.63 s | 2.25 s |
| 3 | 20.42 s | 21.66 s | 2.36 s |

The short-range job downloaded its scene once (5.26 s). Nevertheless, the current worker launches a **new Blender process for every frame**. The falling frame times do not prove persistent scene reuse, nor that every frame after frame 4 or 5 will have the same cost. Different frames and system caches can affect timing; the records do not isolate the cause.

## Estimating a longer job

```text
frame_count = duration_seconds × frames_per_second
estimated_worker_cost = worker_seconds / 3600 × hourly_rate
estimated_total_seconds = frame_count × measured_mean_worker_seconds_per_frame
```

For illustration only, 10 minutes at 24 fps is **14,400 frames**. Repeating the entire three-frame Junk Shop job's average would imply approximately **176.08 worker-hours (7.34 days) and USD 132.06 at USD 0.75/hour** on one worker. Using only its render + save component gives about USD 100.75, but that omits other execution work. Neither figure is a quote for a film: three frames are not representative of changing shots, simulations or difficult frames, and a larger batch has different overhead.

This duration also exceeds the add-on's current 24-hour maximum per request. Split long sequences into suitable ranges and allow for the provider's execution/TTL limits. Automatic chunking and parallel distribution are not implemented.

Worker execution estimates omit costs not captured by that timer, potentially including worker startup, idle tail, storage, retries and applicable taxes. The addon does not separately measure startup and shutdown charges. Check [RunPod billing rules](https://docs.runpod.io/serverless/pricing) and your account's actual billing records.

## Traditional render farm price references

Checked 2026-11-10 on the providers' own pages. Rates below are advertised rates, not measured costs for these scenes. Discounts, taxes, priority, supported features and billing rules can change.

| Provider | Published GPU rate | Unit / qualification |
| --- | ---: | --- |
| [GarageFarm](https://garagefarm.net/pricing) | USD 0.004 low / 0.006 medium / 0.012 high | Per OctaneBench-hour (OB·hour) |
| [Super Renders Farm](https://superrendersfarm.com/pricing) | USD 0.003 | Per OctaneBench-hour; advertised GPU rate |
| [RebusFarm](https://rebusfarm.net/buy) | 0.53 cent | Per OB·hour as displayed on the retrieved pricing page; confirm checkout currency and RenderPoint conversion |

The simple unweighted mean of the **two directly quoted USD entry rates** (GarageFarm low and Super Renders) is **USD 0.0035/OB·hour**, with a range of USD 0.003–0.004. This is a small convenience sample, **not an industry average**, and is not comparable directly to USD 0.75 per GPU-hour.

For a purely illustrative **600-OB node**, those two rates imply USD 1.80–2.40 per node-hour, a sample mean of USD 2.10. One minute on that hypothetical node would cost USD 0.03–0.04 before other adjustments. This is **not a quote for either Blender scene**. OctaneBench is not a Cycles performance conversion, and the actual RunPod card in our tests is unknown.

**Measured farm cost for Junk Shop and Panthera: not available.** We have not sent these matched scenes to the listed farms. An honest per-frame comparison requires the same file, frame, Blender version, engine, samples, denoising and output settings to be tested on each service. Managed farm prices can also include integration, support and parallel scheduling that this add-on does not provide.

## How to improve the benchmark

Record the GPU model, driver, worker image digest, Blender versions, source-file hash, render settings, cold/warm state and actual billing. Run the same frame multiple times and a representative animation range; report medians and variation. Compare both render-only and end-to-end time. Keep failures and retries in the cost accounting. Verify image equivalence before claiming a speed or savings advantage.

The [README affiliate disclosure](../README.md#support-development) applies to the RunPod referral link. It is not evidence of price or performance superiority.
