# Privacy policy

Effective date: 2026-11-10. Application: **Easy RunPod for Blender Render**. Maintained through [TonyDark0/Easy-Runpod-for-Blender-Render](https://github.com/TonyDark0/Easy-Runpod-for-Blender-Render). Contact: [theborderculture@gmail.com](mailto:theborderculture@gmail.com).

## What the application accesses and why

The add-on connects Blender to your own RunPod account and Google Drive to render your selected scenes. It processes your RunPod API key, Google OAuth authorization, basic Drive account information (including the email address and account permission identifier), selected scene snapshots and caches, render settings, output images, file/folder identifiers, job status and render timings.

Google Drive access uses `https://www.googleapis.com/auth/drive.file`. It is used to create and manage the app's render folders, upload scene snapshots and caches, retrieve them on your worker, save rendered images and status, and download results to your computer. It does not request unrestricted access to all files in your Drive. Account information is used to display the connected account and identify whether a previous app folder can be reused.

## Where data goes

- **Your computer:** Blender preferences hold the RunPod API key and settings. A separate configuration file holds Google authorization and connected-account details. Local job history contains file identifiers, paths, settings and timing data. Downloaded images and reports go to your chosen folder.
- **Google:** OAuth authorization is handled by Google in your browser. Scene snapshots, cache archives, images and job status are stored in your Drive account. The app does not automatically make them public.
- **RunPod:** Your configured worker receives the Google client details and refresh token so it can access app-authorized Drive files without Blender remaining open. Scene and cache data are downloaded to the worker for processing; RunPod also receives API requests and execution metadata.

The current architecture does not send your render files or credentials to a maintainer-operated backend, include analytics telemetry, sell Google user data, use it for advertising targeting or use it to train AI models. Google, RunPod and GitHub operate their own services under their respective policies. Account administrators or other people with access to your computer, Drive or RunPod configuration may have access to that data.

## Storage and security

Connections use HTTPS except the OAuth callback on the local loopback interface. OAuth uses state validation and PKCE. New Windows Google credential writes use the signed-in user's DPAPI protection; legacy plaintext credentials are rewritten when you reconnect. On other systems the current implementation uses a local file with restrictive creation permissions. The RunPod key is masked in the UI but stored in Blender preferences. Worker credentials remain in your RunPod configuration. No claim of end-to-end encryption is made.

The manual **Copy worker credentials** action places authorization information on your clipboard. Do not share it publicly. Scene snapshots can contain sensitive project assets; upload only material you are authorized to process on these services.

## Retention, disconnecting and deletion

Drive scenes, caches, results and status remain until you delete them. Cancelling a job does not delete completed uploads. Local history, settings and downloads remain until removed. Worker temporary files are normally cleaned up when processing ends, but provider infrastructure, logs, failures and retention are governed by RunPod.

**Disconnect on this computer** removes the local Google authorization file only. It does not revoke Google's grant, remove the worker credentials, stop remote jobs or delete files. To fully withdraw access:

1. Cancel any jobs you no longer want running.
2. Remove the app's access through [Google Account connections](https://myaccount.google.com/connections).
3. Remove the Drive credential variables or the endpoint in your RunPod account.
4. Delete app-created folders in Drive, local downloads and local configuration/history as desired.
5. Revoke the RunPod API key in RunPod if it is no longer needed.

Revocation prevents future authorized access but does not itself erase copies already stored by you or your providers. The maintainer cannot delete data from accounts it does not control.

## Support and affiliate links

If you contact the maintainer or open an issue, the information you voluntarily send is used to respond and troubleshoot. GitHub issues are public; do not include tokens, credentials or private scene files. Contact the email above about support messages or information you have shared directly.

The RunPod signup link is an affiliate link and may provide referral compensation to the maintainer. Clicking it takes you to RunPod, which handles referral attribution under its own policies. The add-on does not send your Drive content or Google authorization tokens through the affiliate link. A non-affiliate link is also provided.

## Google user-data commitment and updates

The application's use and transfer of information received from Google APIs will adhere to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including its Limited Use requirements where applicable. Google data is used for the user-facing rendering, storage and retrieval functions described here.

Changes to data handling will be reflected in this policy. New purposes or permissions will require an updated disclosure and authorization where applicable. This policy does not mean Google has verified or endorsed the application.
