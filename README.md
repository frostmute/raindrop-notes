# raindrop-notes

Every 30 minutes, a GitHub Action pulls new Raindrop.io bookmarks, takes a screenshot of each page, summarizes it with Gemini, and commits a Markdown note.

- Notes: `notes/YYYY/MM/<title>-<raindrop id>.md` (YAML front matter: title, url, domain, tags, created)
- Screenshots: `screenshots/<raindrop id>.jpg`
- Progress: `state.json` (last bookmark processed)

Secrets: `RAINDROP_TOKEN`, `GEMINI_API_KEY` (AI Studio key, free tier).
Run it now: Actions > Sync Raindrop bookmarks > Run workflow.
Replaces the Pipedream workflow "Raindrop.io to Summarized Markdown with Screenshots" (Pipedream Workflows shut down March 31, 2027).

## Site

Published at https://frostmute.github.io/raindrop-notes/ — a screenshot grid of every bookmark, a page per bookmark (full screenshot, link, summary, tags, related bookmarks), tag pages, search (`/`), keyboard nav (`j`/`k`, `enter`), and an Atom feed at `feed.xml`.

- Generator: `site/build.py` (Python: markdown, jinja2, pyyaml, pillow) reads `notes/` + `screenshots/`, writes `_site/` (not committed). `site/check.py` checks every internal link.
- Templates in `site/templates/`, CSS/JS/fonts in `site/static/`. Anything you add to a note in Obsidian outside the Summary/Excerpt sections shows up on its page.
- Local preview: `pip install -r site/requirements.txt && SITE_BASE=/ python site/build.py && python -m http.server -d _site`
- Deploys: the `pages` job in `sync.yml` publishes after a sync that committed new bookmarks; `pages.yml` publishes on pushes to `main` touching `site/`, `notes/` or `screenshots/`, and on manual runs (Actions > Publish site > Run workflow).
