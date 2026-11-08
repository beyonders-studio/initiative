---
icon: lucide/book-marked
---

# Maintaining these docs

This help center is a static website built with [Zensical](https://zensical.org/) (a static site generator from the team behind Material for MkDocs). This page is for whoever edits or publishes it. If you're just reading the docs, you can ignore it.

## How it's laid out

```text
zensical.toml                 # site configuration (at the repo root)
docs/
├─ index.md                   # language landing — redirects to en/
├─ stylesheets/
│  └─ extra.css               # the "screenshot" and "techspec" callout styles
└─ en/                        # all English content lives here
   ├─ index.md                # home page
   ├─ getting-started/
   ├─ concepts/
   ├─ guides/
   ├─ sharing/
   ├─ security/
   ├─ account/
   ├─ running-a-server/
   ├─ reference/
   └─ images/                 # screenshots, organized by section
```

The navigation menu is defined explicitly in `zensical.toml` under `nav`. When you add a page, add it to `nav` too.

## Editing and previewing

You need Python. Install Zensical once into a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install zensical
```

Then, from the repository root:

```bash
zensical serve     # live preview at http://localhost:8000 (rebuilds as you edit)
zensical build     # build the static site into ./site
```

`site/` and the build cache are git-ignored — don't commit them.

## Writing conventions

We write for two audiences at once: people who struggle with technical tools, and the more technical project managers and the people who run servers. Two custom callouts keep them separated cleanly.

### Marking where a screenshot goes

Every place that needs an image uses a **screenshot** callout, so missing visuals are easy to find:

```markdown
!!! screenshot "Short description of where this is"
    **Show:** what the picture should contain.

    Save as `en/images/<section>/<name>.png`, then replace this box with:
    `![Alt text](../images/<section>/<name>.png)`
```

It renders as a dashed purple box with a camera icon. When you have the real image:

1. Save it under `docs/en/images/<section>/` (create the section folder if needed).
2. Replace the callout with the image line it shows — for a page in any section folder, the path is `../images/<section>/<name>.png`; the home page (`en/index.md`) uses `images/<section>/<name>.png`.

!!! tip "Keep images reasonably sized"
    Crop to what matters and export PNGs at a sensible width. Huge images slow the page down. You can constrain width with `![Alt](path){ width="700" }`.

### Marking technical detail

Detail aimed at technical readers goes in a **techspec** callout, usually collapsed so everyone else can skip it:

```markdown
??? techspec "For the technically minded — heading"
    The precise detail goes here.
```

It renders as a teal box with a wrench icon. Use `???` for collapsed and `!!!` for always-open.

### Questions in the FAQ

Each question is a `###` heading under its topic's `##` heading, with the answer beneath it as ordinary paragraphs:

```markdown
## Getting in

### My invite link doesn't work

Links can expire, run out of uses, or be switched off by an admin.
```

Search in the app's **Help** panel finds pages by their headings, so a question written as a heading turns up there on its own. One tucked inside a collapsible block doesn't.

## Adding another language

The content is deliberately kept under `docs/en/` so more languages can be added without moving anything. To add, say, Spanish:

1. Copy `docs/en/` to `docs/es/` and translate the pages (images in `en/images/` can be shared).
2. Add a parallel `nav` block (or switch to a language-aware navigation) in `zensical.toml`.
3. Add a language switcher and turn the root `docs/index.md` into a real chooser.

!!! info "Built-in multi-language support is on the way"
    At the time of writing, Zensical's per-language content plugin is on its roadmap rather than shipped, which is why the language switch is wired up by hand. When it lands, the per-language folder layout here is exactly what it expects, so the move will be small.

## Publishing

A GitHub Actions workflow (`.github/workflows/docs.yml`) builds the site and deploys it to **GitHub Pages** when documentation files change on `main`. To use it, enable Pages for the repository (**Settings → Pages → Source: GitHub Actions**). Don't want to publish from CI? Delete that workflow and host the contents of `site/` anywhere that serves static files.

The workflow also publishes the search in the app's **Help** panel: `backend/scripts/build_help_index.py` trims the build's `search.json` to a title, a breadcrumb, an address and a snippet per heading and writes it beside the pages as `help-index.json`, which every server's Help panel reads. Zensical is pinned in the workflow because the script reads that file. If a new version writes `search.json` in a shape the script doesn't recognize, the deploy stops with an error rather than publishing an empty search.

Before publishing for real, set `site_url` in `zensical.toml` to the final address — it powers search, the sitemap, and link previews.
