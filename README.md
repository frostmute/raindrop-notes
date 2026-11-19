# raindrop-notes

Every 30 minutes, a GitHub Action pulls new Raindrop.io bookmarks, takes a screenshot of each page, summarizes it with Gemini, and commits a Markdown note.

- Notes: `notes/YYYY/MM/<title>-<raindrop id>.md` (YAML front matter: title, url, domain, tags, created)
- Screenshots: `screenshots/<raindrop id>.jpg`
- Progress: `state.json` (last bookmark processed)

Secrets: `RAINDROP_TOKEN`, `GEMINI_API_KEY` (AI Studio key, free tier).
Run it now: Actions > Sync Raindrop bookmarks > Run workflow.
Replaces the Pipedream workflow "Raindrop.io to Summarized Markdown with Screenshots" (Pipedream Workflows shut down March 31, 2027).
