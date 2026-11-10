# Strategy notes: n8n vs. the CDP worker, and why quality comes from inputs

(Moved out of SKILL.md 2026-11-09 to keep it under the 100K skill_manage limit.)

- n8n is orchestration, not quality — generation quality comes from reference crops, prompt structure, model choice and post-production. n8n buys reliability: parallel takes with best-of selection, retry on Failed cards (one Failed card cost 20 min on 2026-10-27), state/logging, automatic post + notify.
- Flow has no official API, so the honest options are: the existing CDP browser worker (recommended, free), the unofficial `useapi/google-flow-api` (easy n8n fit, **not official — ToS risk**), or the Gemini API (official, paid per second, **loses** the project's characters/ingredients).
- Levers that beat n8n for quality: model upgrade (Omni Flash → Veo 3.1 Fast/Quality = 100 cr/8 s), Frames-to-video chaining, free 1080p upscale, multi-take + pick.

## Clearing browser state on the Flow profile (2026-11-09)
- Deleting cookies for `google.com` / `flow.google.com` logs the profile out of Google. The agent cannot complete a Google login on its own (no password entry, no display for the user), so get the user to be ready to sign in before clearing, and state that in the ask.
- Working path from the CDP side: `Network.getAllCookies` → filter by domain → `Network.deleteCookies(name, domain, path)` per cookie. `Storage.clearDataForOrigin` returned `Internal error` on this Chrome build, and `Network.clearBrowserCache` timed out, so cache clearing was not verified.
- A Chrome relaunch on the same profile opens the Google sign-in page; the profile does not keep Flow PRO until that login is finished.
