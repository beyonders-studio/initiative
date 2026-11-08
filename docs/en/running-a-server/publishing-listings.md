---
icon: lucide/package-plus
---

# Publishing your own listings

Initiative's marketplace ships with a set of ready-made dashboards, projects and plug-ins. It's also **yours to add to**, and there are two ways in:

| | **Your own directory** | **The Initiative registry** |
|---|---|---|
| Who sees it | Your server | Every server that follows the registry |
| How | Drop a listing file in a folder | A pull request |
| Who decides | You | The registry's reviewers |

Neither needs a fork, a code change, or a new build of Initiative. If you've built a project your group sets up from scratch every spring, or someone has published a listing file you'd like to run, this is how it gets in. Most of this page is the directory; [the registry](#publishing-to-the-initiative-registry) is at the end, and takes the same file.

!!! info "Where the trust comes from"
    You control the directory, so a file being in it *is* your decision to publish it. Every listing is shown with the publisher named in its own file, wherever it appears — on the card, on its page, and in the dialog where someone adds it — so the question of who made it is answered at the moment of the decision. Listings that ship with Initiative are credited to Initiative, and a listing you add can't claim that credit (see [Reserved names](#names-you-cant-use)).

## Turning it on

Set `MARKETPLACE_EXTRA_CATALOG_DIR` to a directory inside the container, and mount your own folder there:

```yaml
services:
  initiative:
    environment:
      MARKETPLACE_EXTRA_CATALOG_DIR: /app/marketplace-catalog
    volumes:
      - ./marketplace-catalog:/app/marketplace-catalog
```

Leave the variable unset — the default — and none of this happens: no directory is read and your marketplace shows the built-in listings only.

Initiative reads the directory **every time it starts**. Only `*.json` files are read, so a `README.md` or an image sitting alongside them is ignored rather than reported as a mistake.

## What a listing file looks like

One file per listing. Here's a complete dashboard listing:

```json
{
  "uid": "K7M2QX8N4TVB9C",
  "public_id": "acme.standup",
  "kind": "dashboard",
  "name": "Standup board",
  "publisher": "Acme Engineering",
  "description": "What everyone is on today.",
  "long_description": "A single screen for the morning standup: what's in flight, what's blocked, and how the week is tracking.",
  "avatar_url": "/marketplace/acme-standup.svg",
  "images": [],
  "version": "1.0.0",
  "release_notes": "First release.",
  "definition": {
    "schema_version": 1,
    "kind": "dashboard",
    "layout": { "columns": 12 },
    "widgets": [
      {
        "id": "w1",
        "type": "stat",
        "title": "Open tasks",
        "grid": { "x": 0, "y": 0, "w": 4, "h": 2 },
        "binding": { "source": "task_counts" }
      },
      {
        "id": "w2",
        "type": "gantt",
        "title": "This week",
        "grid": { "x": 4, "y": 0, "w": 8, "h": 6 },
        "binding": { "source": "tasks" }
      }
    ]
  }
}
```

| Field | Required | What it is |
|---|---|---|
| `uid` | ✅ | The listing's product code — see [Choosing a uid](#choosing-a-uid). |
| `public_id` | ✅ | A readable id, `<publisher>.<slug>`. Lowercase letters, digits, `.`, `-` and `_`. |
| `kind` | ✅ | `dashboard`, `project`, `plugin` or `home_layout`. |
| `name` | ✅ | What the card is called. |
| `publisher` | ✅ | Who publishes it, as one name: a person, a team, an organization. |
| `description` | ✅ | The one-line blurb on the browse card. |
| `long_description` | | The longer text on the detail page. |
| `avatar_url` | | The listing's artwork — see [Artwork](#artwork). Left out, it gets a plain default. |
| `images` | | Screenshots for the detail page, same rules as `avatar_url`. |
| `version` | ✅ | The version this file publishes, e.g. `1.2.0`. |
| `release_notes` | | What changed, shown beside the version. |
| `min_app_version` | | The oldest Initiative this version runs on. Newer-than-you versions are shown as needing an update rather than hidden. |
| `min_plugin_api` | | For a plug-in: the oldest plug-in API it needs, as `MAJOR.MINOR` (e.g. `4.1`). The plug-in API is versioned as the plug-in SDK, and this server provides the one its build vendors. It runs a version needing the same major and at most its minor; any other is shown but can't be installed. The plug-in's manifest may say the same, and the two must agree. |
| `definition` | ✅ | The body — what installing actually produces. For a project, see [A project listing](#a-project-listing). |
| `example` | | A project listing's filled-in example. |
| `registration` | | A plug-in listing's facts — see [A plug-in listing](#a-plug-in-listing). |

Everything is checked before it's published, by the same validation the built-in listings go through. A file that doesn't pass is skipped with the reason recorded, and the listings around it publish normally.

### Attribution is required

**A listing states who publishes it, or it isn't published.** `publisher` is not optional, on any route into the catalog. People decide whether to install something based on who it's from, so the question is answered on the card, the detail page, and the install dialog — always next to where the listing came from, so a name never stands in for provenance.

### Names you can't use

`core.*` belongs to the listings Initiative ships. A file in your directory claiming a `core.` public id is refused, and named in the scan result, so an id can never imply an origin the listing doesn't have. Publish under your own prefix instead: an organization name, a domain, a team.

A uid or public id already published by another source — a built-in, or a registry your deployment follows — is also refused rather than quietly taken over. Two listings claiming the same identity is a mistake worth seeing.

## A project listing

A project listing's `definition` is the file you get from **Export** in a project's **Settings → Advanced** — the same file that imports back in. So the quickest way to write one is to build the project in Initiative, export it, and paste the file in.

What installs is a new project of the installer's own, called whatever the listing is called, laid out the way you laid yours out: its board's cards, its table's columns, its task page and the list it opens on. Four things in the file don't travel:

- **People.** Assignees, attendees, person fields and the people a preset picks out are left out, since the people in your community aren't the people in theirs.
- **Plug-ins** on its layouts. The installer's community has its own, and the ones placed in their initiative show up on the new project.
- **Links and uploads** pointing at things in your community.
- **Dates, as dates.** They're kept as distances from each other, and the installer picks a **Start date** that the earliest one lands on. A launch plan with a deadline six weeks in stays six weeks in.

Writing `layouts` by hand? A layout names a status or a property by its place in the file's own lists, counting from 1: a status id of `2` is the second of `task_statuses`, and `property:3` the third of `property_definitions`.

Give the project its own `task_types`, or it installs with the four every new project starts with. Each type has a shape (`layout_preset`: `plain`, `fix`, `discussion`, `dates`, `repeat` or `checklist`) and can bring `starting_values`, such as a checklist or a repeat, for the tasks people add later. A task names its type with `type_name`. Each type can have its own task page: a `task` layout whose `task_type` is the type's place in `task_types`, counting from 1. A page that leaves out `main` keeps its shape's.

`example` is optional, and is a second export of the same project with some work filled in: a few tasks moving through the board, so the shape makes sense at a glance. The listing's page then shows **Blank** and **Example** side by side, and the installer chooses which to start from.

## A home layout listing

A ready-made home page that people add to their own home as a new view. Its `definition` places widgets on a twelve-column grid; `y` and `h` count rows.

```json
"definition": {
  "schema_version": 1,
  "kind": "home_layout",
  "widgets": [
    { "id": "clock", "type": "clock", "grid": { "x": 0, "y": 0, "w": 4, "h": 6 },
      "options": { "mode": "timer", "timer": { "duration": 1500 } } },
    { "id": "focus", "type": "focus", "grid": { "x": 4, "y": 0, "w": 8, "h": 6 } }
  ]
}
```

Widgets are `greeting`, `gettingStarted`, `focus`, `tasks`, `comingUp`, `calendar`, `recent`, `activity`, `communities`, `progress` and `clock`. Each has a smallest size, and `greeting`, `gettingStarted`, `focus`, `tasks`, `calendar`, `communities` and `progress` may appear once. Two widgets can't share a cell.

Only options that mean the same on anybody's page are accepted:

| Widget | Options |
|---|---|
| `greeting` | `yonder`: `true` or `false` |
| `comingUp` | `days`: `3`, `7`, `14` or `30` |
| `recent` | `mode`: `viewed` or `changed`; `tools`: a list of tool kinds |
| `activity` | `view`: `all` or `yours` |
| `clock` | `mode`: `clock` or `timer`; `zones`: up to three time zones; `timer`: `{ "duration": <seconds> }` |

Anything that would point at one person's own things — a community, a list, a note — is refused, as is a widget this server doesn't draw. The refusal names the widget and the reason.

## A plug-in listing

A plug-in's `definition` is its manifest, as the [plug-in SDK](https://github.com/beyonders-studio/initiative-plugin-sdk) builds it. Its `registration` says how it runs and the most it may ever be granted:

```json
"registration": {
  "kind": "container",
  "image": "ghcr.io/acme/tracker@sha256:…",
  "scope_ceiling": ["projects:read", "comments:write"]
}
```

| Field | What it is |
|---|---|
| `kind` | `container` for one that runs as its own program, `declarative` for one Initiative runs itself. |
| `image` | A container's image, pinned by digest. |
| `scope_ceiling` | Everything it may ever be granted. Its manifest may ask for less, never more. A ceiling in your own directory is your approval of it. |

Where it runs and the keys it signs with aren't in the listing: those belong to each server that runs it. Once the listing is published, the plug-in shows up under **Plug-in services** for you to finish. See [Running plug-ins](plugins.md).

## Choosing a uid

The `uid` is a product code, like a barcode. It identifies the *listing*, so "install `K7M2QX8N4TVB9C`" means the same thing on every Initiative carrying it — which is what makes a listing shareable at all.

- **14 characters**, from `0123456789ABCDEFGHJKMNPQRSTVWXYZ`. The letters `I`, `L`, `O` and `U` are deliberately absent so a code can be read aloud or copied by hand without confusion.
- **You assign it**, once, when you first publish. Generate 14 random characters from that set.
- **It never changes and is never reused.** Editing the listing keeps the uid; a genuinely different listing gets a new one.

## Artwork

`avatar_url` and `images` are **paths on your own Initiative**, not links to other sites — so no listing can pull in an image from somewhere else. Each must start with `/` and use only letters, digits, `/`, `.`, `-` and `_`.

Put the files where Initiative serves its static assets, under `marketplace/`:

```yaml
volumes:
  - ./marketplace-catalog:/app/marketplace-catalog
  - ./marketplace-art:/app/static/marketplace
```

A file at `./marketplace-art/acme-standup.svg` is then reachable at `/marketplace/acme-standup.svg`, which is what the manifest above names. SVG and PNG both work; square artwork looks best on the cards.

## Publishing an update

Edit the file and bump `version`:

- **A version is immutable once published.** Re-publishing the same version string with different content is refused — bump it instead. This is what lets a community pin a version and trust it stays what they installed.
- **The listing's name, blurbs and artwork are editable in place**, with no version bump. Fixing a typo in a description doesn't need a release.
- **Nothing is pushed into a community.** An installed dashboard keeps running the version it pinned; communities see an *update available* badge with your release notes and choose when to take it.

## Removing a listing

Delete the file. On the next scan the listing is **withdrawn**: it disappears from browse and can't be installed again.

Withdrawn isn't deleted. Communities that already installed it keep what they installed, working exactly as before, along with the record of where it came from — removing a listing from your catalog never reaches into a community and takes something away. Put the file back and the listing is published again.

A file that's *present but broken* is not a removal: it still claims its listing, so a manifest you're in the middle of editing leaves the existing listing alone rather than pulling it while you work.

## Picking up changes without a restart

Restarting Initiative rescans the directory. To pick up a change immediately, the [owner](platform-roles.md) can trigger a rescan on demand:

```bash
curl -X POST https://your-initiative.example.com/api/v1/marketplace/operator-catalog/rescan \
  -H "Authorization: Bearer $TOKEN"
```

The response says what happened, and names any file it skipped:

```json
{
  "published": 3,
  "withdrawn": 1,
  "skipped": 1,
  "problems": [
    { "file": "draft.json", "reason": "draft.json is not valid JSON: Expecting ',' delimiter: line 9 column 3" }
  ]
}
```

Only one scan runs at a time; a second request while one is in flight is refused rather than queued.

## When something doesn't appear

Work down this list — the scan result above answers most of it directly.

| What you see | What it usually means |
|---|---|
| Nothing at all published | The directory isn't mounted where `MARKETPLACE_EXTRA_CATALOG_DIR` points. A rescan says so explicitly. |
| One file missing, the rest fine | That file was skipped. Its name and the reason are in the scan result and the server log. |
| "reserved" in the reason | The `public_id` starts with `core.` — publish under your own prefix. |
| "already published by the builtin catalog" | The `uid` or `public_id` belongs to another listing. Pick a new uid. |
| A listing appears but can't be installed | Its `min_app_version` is newer than this Initiative, its `min_plugin_api` names a plug-in API this Initiative doesn't provide, or a community already has it. |
| A plug-in listing never appears on the Plug-ins shelf | Communities are offered a plug-in only once it's live. Its row under **Plug-in services** says what it's waiting for — see [Running plug-ins](plugins.md). Dashboards and projects need nothing of the sort. |
| Artwork is a broken image | The file isn't under the static `marketplace/` directory, or the path in the manifest doesn't match its name. |

## Publishing to the Initiative registry

The registry is a catalog every Initiative server follows unless its owner switched it off, so a listing there reaches people you'll never meet. Getting one in is a pull request to [initiative-developer](https://github.com/beyonders-studio/initiative-developer), and the review of that pull request is the listing's review.

1. **Add your listing** under `registry/sources/<publisher>/<uid>/`: a `listing.json`, and its artwork and screenshots beside it in `assets/`. The registry's [README](https://github.com/beyonders-studio/initiative-developer/tree/main/registry) has the format, which is this page's with images as files rather than paths on a server, and a complete example to copy.
2. **A new publisher needs a record** in `registry/publishers/` too, and the registry's maintainers sign it before anything under that name publishes. Your prefix is then yours alone: nobody else can publish under it.
3. **Open the pull request.** The checks build and verify the whole catalog with your listing in it, so a mistake shows up there rather than on somebody's server.

Merged is published. Servers pick it up at their next check, within fifteen minutes, and show it with your publisher's name.

An update is another pull request that adds a version. The rules are the ones above: a published version never changes, and nothing is pushed into a community that already installed it.

## Related

- [Configuration](configuration.md) — every setting, including `MARKETPLACE_EXTRA_CATALOG_DIR`.
- [Running plug-ins](plugins.md) — finishing a plug-in once its listing is published.
- [Platform roles](platform-roles.md) — who may trigger a rescan.
- [Plug-ins & the marketplace](../guides/plugins-and-marketplace.md) — how your listings look to the people installing them.
- [Tools](../guides/tools.md) — what a dashboard is, from a member's side.
