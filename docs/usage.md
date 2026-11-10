# Setup and usage

## Requirements

- Blender 4.5 or newer; test compatibility with the worker's Blender 4.5.4 before production use.
- A RunPod account with funds and an API key with the required permissions.
- A Google account with sufficient Drive storage and a valid OAuth authorization.
- A saved, self-contained scene with a camera and supported image output settings.

Install the ZIP through Blender's **Install from Disk** menu and enable the add-on. Do not unpack the ZIP first. Updates replace the installed extension; they do not require recreating your RunPod account. Back up important settings and keep the same extension ID (`runpod_render`) when updating.

## 1. Connect Google Drive

The distributed development ZIP does not yet bundle a production OAuth client. For this build:

1. In your Google Cloud project, enable the **Google Drive API**.
2. Configure Google Auth Platform and create an OAuth client of type **Desktop app**.
3. If the app is in Testing, add your account as a test user.
4. In the add-on's **Preferences → Advanced**, select the downloaded **Google desktop OAuth JSON**.
5. Set the desired **Root folder name**, then select **Connect Google Drive** and authorize in your browser.

The requested scope is `https://www.googleapis.com/auth/drive.file`. It limits access to files created or authorized for the app; it does not grant access to every file in your Drive. The add-on creates its root folder. The current UI does not include a Google Picker for arbitrary existing folders.

Testing authorizations for this Drive scope expire after seven days, including refresh tokens. Reconnect when required, then update the worker's authorization. Public app publication is separate from verification; see the [Google checklist](google-publishing.md) and [Google's audience rules](https://support.google.com/cloud/answer/15549945?hl=en).

## 2. Configure RunPod

### New managed worker

1. Enter your **RunPod API key** in the add-on preferences. Provisioning requires management permissions; a key limited to running jobs on an existing endpoint cannot create a new endpoint.
2. Choose **24 GB - availability** or **RTX 4090 - 24 GB**. MIG devices are excluded from the availability profile.
3. Select **Worker disk (GB)** and **Maximum job duration (minutes)**. Disk must fit the scene, downloaded cache archive, unpacked caches and temporary output.
4. Select **Review worker setup** to fetch the current GPU catalog and rate. Quotes expire after five minutes.
5. Select **Set up worker**. This sends the Drive authorization to your RunPod worker configuration and saves the returned endpoint ID.

The setup uses the maintained Blender 4.5.4 image, zero permanent workers, one maximum worker, one GPU per worker and a five-second idle timeout. It does not submit a test render. **The automated setup is implemented and locally tested, but a live end-to-end onboarding validation remains pending.**

If creation times out, inspect your RunPod console before trying again: the resource may have been created even if its response was lost. Automatic duplicate recovery is not implemented. Updates to a managed endpoint refuse to proceed when its health response reports queued or running jobs.

### Existing endpoint

Enter its ID in **Advanced**, then use **Check RunPod connection**. Install the project's worker image and configure `DRIVE_CLIENT_ID`, `DRIVE_CLIENT_SECRET` and `DRIVE_REFRESH_TOKEN` in that endpoint. **Copy worker credentials** is the manual helper for this path; its clipboard contents are sensitive. Do not paste them into issues or chat.

The automated setup deliberately refuses to overwrite an existing endpoint that it did not create. It also does not enforce scaling settings on manually configured endpoints: verify **0 active / 1 maximum worker** in RunPod yourself.

After reconnecting Google, use **Update worker** for a managed endpoint, or replace the three Drive variables for a manually configured endpoint. Connecting Google locally does not silently replace the worker's credentials.

## 3. Prepare a scene

Save the `.blend` and set a camera. Use Blender's external-data packing tools for supported assets. Check linked libraries, textures and simulation dependencies. Appended data can retain historical source references that are not live dependencies; the preflight excludes known weak references.

Bake simulations that need a consistent state across frames. Detected Ocean, fluid and supported point-cache folders are bundled automatically. **Add cache folder** includes additional folders associated with the current scene. It is not a universal resolver for third-party add-on paths or arbitrary file dependencies. Linked cache properties that cannot be remapped must be made local.

Whole cache folders are uploaded, even for a short requested range. An in-memory particle cache is not equivalent to a transferable disk bake. Missing files and unsupported dependencies must be resolved before submission. **Check scene** performs preflight checks without starting a GPU; it cannot prove that every scene feature will render correctly remotely.

## 4. Send a still or animation

In **Render Properties → RunPod Render**:

- Use **Current Blender file** to upload a fresh snapshot with its current settings and caches.
- Use **Uploaded scene** to select a previous snapshot belonging to this file. Local edits are not included. The snapshot's render settings remain in effect.
- **Render current frame** uses the current local timeline frame number.
- **Render animation** uses **Scene range** or **Custom range**. For an uploaded snapshot, Scene range uses stored metadata when available; older jobs fall back to their submitted range.

The worker uses the saved scene's image settings, with the exceptions documented in the [limitations](roadmap.md). Files are named `frame_0001.ext`, etc. Each job gets its own Drive folder based on the Blender filename; duplicates receive numeric suffixes. Reusing a snapshot does not upload another `.blend` or cache archive, but the worker still downloads the source files for the new job.

Wait for submission to succeed before closing Blender. Uploading the source is not the same as submitting the render request.

## 5. Monitor, cancel and retrieve

The progress bar counts requested frames whose outputs are recorded in Drive, such as **4/11 frames completed**. It does not show Cycles sample progress inside the current frame. Automatic polling runs approximately every 60 seconds while Blender is open and idle enough to perform the request, and after loading a file.

**Cancel process** interrupts local preparation between safe checkpoints or sends a remote cancellation request. An in-flight network request may finish before cancellation takes effect. Completed outputs are retained; GPU time already used may still be charged. If cancellation fails, the job card shows the error.

Use **Open Drive**, **Download results**, **Open result**, **Import into Compositor** or **Download report**. The current compositor import creates individual image nodes; automatic image-sequence assembly is a future improvement. Automatic downloading requires a configured local destination and Blender to remain open.

Failed, cancelled or timed-out jobs can use **Retry missing frames**. The worker skips outputs already recorded in the job's status. Retrying is a new billable request; there are no automatic render retries.

## History and migration

Jobs are stored locally in Blender's configuration directory and filtered using an identity derived from the full `.blend` path. Identically named files in different folders are distinct. Closing and reopening the same path preserves its history. Moving, renaming or using Save As creates a different identity; cross-computer history recovery is not implemented.

Older jobs without an identity remain available in **Preferences → Advanced → Unassigned jobs from older versions**. Open the intended `.blend` and explicitly assign the correct jobs. Do not identify them by basename alone.

## Common issues

| Symptom | What to check |
| --- | --- |
| Google sign-in is not configured | Select your Desktop OAuth JSON in Advanced in the development build. |
| Google authorization expires | Reconnect, then refresh the worker credentials; Testing tokens are short-lived. |
| Setup reports insufficient permissions | Use a key with endpoint-management access for setup. |
| Missing external resources | Pack supported assets and include actual baked cache directories. |
| Job remains queued | Check GPU availability, funds and worker logs in RunPod. |
| Local and cloud images differ | Match Blender versions/settings and account for disabled compositing and sequencer. |
| Work finishes but status is stale | Reopen the file, check network/Drive authorization and inspect the job's report. |
| Estimated cost differs from billing | Reports use a USD 0.75/hour reference, not your actual invoice. |

Support: [GitHub Issues](https://github.com/TonyDark0/Easy-Runpod-for-Blender-Render/issues) or [theborderculture@gmail.com](mailto:theborderculture@gmail.com). Redact credentials and private assets before sharing diagnostic information.
