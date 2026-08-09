# GitHub-only version — hosted entirely on GitHub Pages

No WordPress, no FTP, no server of your own at all. GitHub hosts the pages
directly and refreshes them on a schedule. You get one link to share.

## What's in this version

- **`index.html`** — a small landing page with two links
- **`tournaments.html`** — every upcoming UK tournament
- **`pinball-republic.html`** — just the Pinball Republic ones
- **`fetch_ifpa_uk_tournaments.py`** — pulls fresh data from the IFPA API
- **`.github/workflows/deploy-pages.yml`** — runs the script on a schedule
  and publishes the result to GitHub Pages

## One-time setup (about 5 minutes)

### 1. Create a GitHub repo
github.com → New repository. **This one needs to be public** (or you need
GitHub Pro/Team/Enterprise) for GitHub Pages to serve it for free at a
`github.io` URL.

Upload these files, keeping the folder structure:
```
your-repo/
├── index.html
├── tournaments.html
├── pinball-republic.html
├── fetch_ifpa_uk_tournaments.py
└── .github/
    └── workflows/
        └── deploy-pages.yml
```

### 2. Add your IFPA key as a secret
Repo → **Settings → Secrets and variables → Actions → New repository secret**
→ name it `IFPA_API_KEY`, paste your key. That's the only secret this
version needs — no FTP credentials at all.

### 3. Turn on GitHub Pages
Repo → **Settings → Pages** → under "Build and deployment", set
**Source** to **GitHub Actions**. (Not "Deploy from a branch" — this
version deploys straight from the workflow.)

### 4. Run it
Repo → **Actions** tab → "Refresh and Publish to GitHub Pages" →
**Run workflow**. First run takes a minute or two. After that it runs
automatically every day at 06:00 UTC (edit the `cron:` line in
`deploy-pages.yml` to change the schedule).

**If "Refresh and Publish to GitHub Pages" doesn't appear as a workflow in
the Actions tab** (just shows up as a plain file when you browse the
repo's code instead), the file isn't sitting at the exact path GitHub
requires. Check with:
```bash
git ls-files | grep workflow
```
It must print exactly `.github/workflows/deploy-pages.yml` — no other
folder in front of `.github`. If it's nested inside a subfolder (a common
result of dragging a whole unzipped folder into GitHub's web uploader
instead of its contents), move it up to the repo root and push again.

## Your link

Once the first run finishes, your site is live at:

```
https://<your-github-username>.github.io/<your-repo-name>/
```

That's the one link to share — it lands on a small page with two buttons,
one for the full UK calendar, one for Pinball Republic only. Or link
straight to either page:

```
https://<your-github-username>.github.io/<your-repo-name>/tournaments.html
https://<your-github-username>.github.io/<your-repo-name>/pinball-republic.html
```

If your repo is named e.g. `uk-pinball-calendar` under username `neilmc`,
that's `https://neilmc.github.io/uk-pinball-calendar/`.

## Notes

- **Public repo required** for free Pages hosting. The API key stays safe
  either way — it's a GitHub secret, never exposed in the public repo or
  in the published pages.
- **No custom domain needed**, but if you want one later (e.g.
  `calendar.pinballrepublic.co.uk`), GitHub Pages supports that too —
  just ask and I'll add the config for it.
