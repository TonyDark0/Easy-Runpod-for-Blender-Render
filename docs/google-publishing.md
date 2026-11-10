# Google OAuth publication checklist

## Project identity

- App name: **Easy RunPod for Blender Render**
- Project reference: https://github.com/TonyDark0/Easy-Runpod-for-Blender-Render
- Support and developer contact: **theborderculture@gmail.com**
- Privacy reference: https://github.com/TonyDark0/Easy-Runpod-for-Blender-Render/blob/main/docs/privacy.md
- API: Google Drive API
- OAuth client type: Desktop app
- Audience: External
- Requested scope: `https://www.googleapis.com/auth/drive.file`

These values are prepared for the maintainer. Committing this document does **not** update Google Cloud, publish the app or complete verification.

## Recommended release order

1. Publish accurate usage, privacy and support information in the repository.
2. Validate automated RunPod setup with the existing Google test authorization, including reconnection and a small paid render with an explicitly chosen budget.
3. Configure the Google project's app identity and scope declarations. Confirm the contact email is selectable and monitored.
4. Review Google's homepage/domain requirements before using the repository URLs in an OAuth submission. A GitHub repository is a useful project reference, but owning a repository does not prove ownership of `github.com`. If required, host the homepage and privacy policy on a site/domain whose ownership can be verified; GitHub Pages can host the files, subject to Google's ownership requirements.
5. Move the External app from Testing to In production when ready. Publishing changes the test-user-list restriction; it is separate from brand/scope verification.
6. Complete any required brand verification. Keep `drive.file` rather than requesting full-Drive access. Test sign-in with an account that was not a tester and check any account/Workspace restrictions.
7. Package the project-owned Desktop OAuth client in the add-on and test the full flow without asking users to supply JSON.

Google classifies `drive.file` as non-sensitive. Do not assume that a sensitive-scope warning or its user cap necessarily applies to this scope, and do not promise that publication alone makes branding verified. Testing Drive authorizations expire after seven days, so reconnect after the transition and update worker authorization as needed.

Sources: [Google audience and publishing status](https://support.google.com/cloud/answer/15549945?hl=en), [Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), [brand verification and domain requirements](https://developers.google.com/identity/protocols/oauth2/production-readiness/brand-verification), [Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app).
