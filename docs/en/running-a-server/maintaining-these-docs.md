---
icon: lucide/book-marked
---

# Maintaining these docs

This help center is a static site built with [Zensical](https://zensical.org/) from the Markdown under `docs/`. This page is for whoever edits or publishes it. If you're here to read the docs, you've wandered backstage, and the show is that way.

**How to write a page** is the house standard in `.claude/skills/write-docs/SKILL.md`: the four kinds of page, how deep each goes, the voice, and the checks to run before committing. Read it before you change anything here. This page covers the machinery around it.

## How it's laid out

```text
zensical.toml                   # site settings and the nav, at the repository root
docs/
├─ index.md                     # sends visitors on to en/
├─ stylesheets/extra.css        # the screenshot and techspec callouts
├─ images/                      # the logo, the favicon, and releases/ for the changelog's pictures
└─ en/                          # every English page
   ├─ index.md                  # the home page
   ├─ getting-started/  concepts/  guides/  sharing/
   ├─ account/  security/  running-a-server/  reference/
   ├─ faq.md  self-host-or-hosted.md
   └─ images/<section>/         # screenshots, one folder per section
```

The menu is the explicit `nav` list in `zensical.toml`. A page that isn't in it doesn't appear, so add every new page there, nested where it belongs.

`docs/images/releases/` holds the pictures the changelog shows under its entries. The app loads them from the published site, and `frontend/src/lib/releaseImages.test.ts` fails when a picture the changelog names is missing.

## Building and previewing

You need Python. Install Zensical once:

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install zensical
```

Then, from the repository root:

```bash
zensical build                      # builds into site/, and checks every link and heading anchor
zensical serve -a 127.0.0.1:8080    # live preview that rebuilds as you edit
```

Use port 8080, because the backend's dev server holds 8000. `zensical build` reports a link to a missing page or anchor as an issue, so a clean build means something. `site/` and the build cache are ignored by git.

## The two callouts

`docs/stylesheets/extra.css` styles two callouts of our own.

A **screenshot** callout marks where a picture is still needed, as a dashed purple box with a camera:

```markdown
!!! screenshot "Where this is"
    **Show:** what the picture should contain. Save as `en/images/<section>/<name>.webp`.
```

A **techspec** callout holds detail for technical readers, as a teal box with a wrench. `???` starts it collapsed and `!!!` open:

```markdown
??? techspec "The detail"
    The precise detail goes here.
```

## Pictures

A picture of the app is taken by a script, so it can be taken again whenever the screen changes. Each one is a short Playwright walk in `frontend/e2e/shots/help/<name>.shot.ts` that opens the screen and calls `shootHelp(page, "<section>/<name>")`, or `shootHelp(page, "<section>/<name>", locator)` to crop to one part of it. Run them against a dev environment with its seed data:

```bash
cd frontend
pnpm screenshots e2e/shots/help                      # every help picture
pnpm screenshots e2e/shots/help/tag-page.shot.ts     # one
```

Each shot saves a light and a dark copy, `docs/en/images/<section>/<name>.webp` and `<name>.dark.webp`. The page shows the one that matches the reader's theme:

```markdown
![Alt text](../images/<section>/<name>.webp#only-light)
![Alt text](../images/<section>/<name>.dark.webp#only-dark)
```

That path is from a page in a section folder; from `docs/en/index.md` it's `images/<section>/<name>.webp`. A shot signs in as a seeded community admin, and `signInAs(page, "user1@example.com")` switches to somebody whose view the picture needs.

A picture has to match the app as it stands, so retake it when the screen it shows changes, and remove it when the screen is gone.

## Adding another language

Everything English lives under `docs/en/` so another language can sit beside it:

1. Copy `docs/en/` to, say, `docs/es/` and translate the pages. Pictures can stay shared in `en/images/`.
2. Add a parallel `nav` block for it in `zensical.toml`.
3. Turn `docs/index.md` into a real language chooser.

The app's Help panel searches only the English pages (`LANGUAGE` in `backend/scripts/build_help_index.py`), so that script needs the new language too.

## Publishing

`.github/workflows/docs.yml` builds the site and deploys it to GitHub Pages when a push to `main` changes `docs/`, `zensical.toml`, `backend/scripts/build_help_index.py` or the workflow, and whenever it's run by hand. It runs only in `beyonders-studio/initiative`, so a fork publishes nothing. Pages has to be set to **Source: GitHub Actions** under the repository's **Settings → Pages**.

Docs changes go to `dev` like everything else, and appear on the site when `dev` reaches `main`. `site_url` in `zensical.toml` names the published address (`https://beyonders-studio.github.io/initiative/`), which search, the sitemap and link previews use.

The same workflow publishes the Help panel's search. `build_help_index.py` turns the build's `site/search.json` into `help-index.json` beside the pages: one entry per page and per heading down to `###`, each with a `title`, a `section` (the last two steps of its breadcrumb), a `location` and a `snippet` of about 200 characters. Every server reads that file, whatever version it runs, so those four fields keep their names. The workflow pins Zensical (`zensical==0.1.0`) because the script reads the file that version writes, and if a newer one writes `search.json` in a shape the script doesn't know, the deploy stops with an error rather than publishing an empty search.
