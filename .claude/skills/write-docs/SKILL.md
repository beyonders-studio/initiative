---
name: write-docs
description: Write or edit the Initiative help center under docs/en/: the house voice, the structural rules, and how to build and check the site. Use when adding a docs page, rewriting one, documenting a new feature, or when the user says docs read dry, corporate, or off-brand.
user-invocable: true
---

# /write-docs: writing the Initiative help center

The docs live in `docs/en/`, are built with [Zensical](https://zensical.org/),
and are navigated by an explicit `nav` list in `zensical.toml`.

This skill is mostly about **voice**, because that's the part that keeps going
wrong. The structural rules are at the bottom and are short.

---

## Who you are writing for

One person. Hold them in your head the whole time:

> A millennial with the tech confidence of somebody who misses their old
> indestructible phone. Fluent in memes and irony, genuinely unsure about
> software. Got volunteered to run the rec league's schedule and is quietly
> worried this is going to be complicated and that they will break it.

Two consequences, and both matter more than they sound:

1. **Warmth is the useful part, not decoration.** For this reader, a dry page
   reads as intimidating. Reassurance is load-bearing documentation.
2. **They find things funny.** Humor lowers the barrier. A page that makes
   them snort is a page they finish reading.

Do **not** write for a developer skimming for an API signature. That reader
wants terseness. Ours wants a friendly human who knows the software.

---

## The voice

### Get the joke from recognition, not from quips

The best line on the whole site was written by the user, not by an AI:

> A group chat is where somebody pastes the thing that should have been a
> document, and six months later everyone is scrolling for it, and Jenny has
> left, and somebody is looking at the printer in a way the printer has done
> nothing to deserve.

That's the standard. It works because it is **specific**, **observed**, and
**escalates**. It names Jenny. Nobody had to be told it was a joke.

More of the register:

- "We know somebody color-coded it in 2019 and nobody remembers what green
  means."
- "Good for the tasks that are secretly three tasks in a trench coat."
- "Counters usually get read from the back of a school gym by somebody who left
  their glasses in the car."
- "Initiative makes project management more tolerable."

Each is one plain sentence with the joke folded into it, written the way the
owner talks.

### Dry, not the AI version of dry

These are the habits that make copy read as written by an AI. Each one has
been on this site, and the owner rejected every one:

- **No em dashes.** Use a comma, a colon, parentheses or a new sentence.
- **No fragment chains or tag-ons.** "Open it. It does the rest." "Move it
  back. Nobody saw." "Also fine." "Still fine." "Sorry." Write full sentences.
- **No "Not X. Y."** "A backup you have never restored is not a safety net.
  It's a hypothesis." Say the thing directly: "Restore a backup once, so you
  know it works."
- **No tidy triads.** Three parallel items for rhythm's sake ("clear,
  specific, focused") is a tell. Use the one or two that are true.
- **American examples, idioms and spelling.** Rec league soccer, community
  theater, the HOA, the PTA bake sale. Never the fete, the rota, panto,
  five-a-side, the allotment or the council. Color, organize, humor, license,
  judgment, behavior.

### Reassure constantly

This reader's default assumption is that they will break something. Tell them
they can't, early and often. The home page leads with **"You cannot break
this"** for exactly this reason. Give explicit permission to stop, to skip a
page, to ignore a feature.

### Techniques that work here

- **Escalate a list.** Make the last item break the pattern.
- **Be absurdly specific.** "A club treasurer" beats "a user". A named year, a
  named day, a named Jenny.
- **Let a bit run one sentence longer than expected**, then stop.
- **Deadpan the ridiculous.** State something silly plainly.
- **Vary sentence length**, in full sentences. A short sentence after a long
  one lands; a run of fragments reads as a gimmick.
- **Name the reader's actual emotional state**, then defuse it.

---

## Keep it brief

Nobody reads a wall of text, our reader least of all. A page that sprawls
gets closed.

So say the thing, then stop.

### Cut explanation, never voice

This is the whole trick, and it's easy to get backwards. Brevity is not a
license to strip the personality back out and leave a spec sheet. The jokes
are what get the page read; the over-explaining is what stops it being read.

When a page is too long, the thing to delete is almost always a paragraph
patiently explaining something the reader would have understood in four
seconds of clicking.

> **Cut this:** "The Access tab allows you to configure permissions for the
> project. Permissions determine which users are able to perform which actions.
> By configuring permissions appropriately, you can ensure that only the
> intended people have access."
>
> **Keep this:** "Open the **Access** tab any time to add people, change a
> level, or remove somebody. Changes apply immediately."

### Trust the software

Somebody who opens the Access tab will see the Access tab. Our job is to tell
them it exists, what it's for, and the one thing that would surprise them.
The screen doesn't need narrating back to them.

Document the **non-obvious**: the thing that catches people out, the reason
behind a design choice, the setting whose name doesn't quite say what it does.
Skip the parts the interface already makes plain.

Over-explaining is worse than under-explaining, because it buries the sentence
that actually mattered.

### Signs a page has got away from you

- A paragraph that could be a table row.
- A sentence restating the heading directly above it.
- Three examples where one specific one would land harder.
- Explaining *what* a button does when the reader can see the button.
- Any run of prose longer than about four lines without a break, list or table.

### Practical shape

- Lead with the answer. Context after, if it's needed at all.
- Prefer a table or a short list to a paragraph, whenever the content has any
  structure at all.
- Two or three sentences per paragraph. Then a break.
- If a guide passes roughly 1,200 words, ask what it's doing. It may genuinely
  need the room, or it may be two pages, or it may just be padded.

**Reference pages are exempt from the word count, not from the rule.** The FAQ
and `running-a-server/publishing-listings.md` are looked *up*, never read start to finish,
so length there costs nothing. Each individual entry still has to be short.

### Don't restate a definition that already has a home

The glossary once held 52 entries, most of them repeating (less well, with
less context) something the owning page already said. That is duplication with
a maintenance bill attached: it drifts silently, and every new tool means
remembering to go and update it. It had already drifted.

It now holds only the words where the everyday meaning **misleads**: community,
initiative, tool, handle, presence, full access, break-glass, archive vs. trash.
A reader can't guess those. They can guess "subtask".

Same test anywhere else: if a page is explaining something another page owns,
link to it instead.

---

## Never do these

Each of these was an actual failure on this site. They are not hypothetical.

### Never patch a dry page with jokes

Voice lives in structure: how a page opens, what it notices, what it lets you
skip. Swapping clauses into a dry page produces a dry page with winking asides
bolted on, which is worse than leaving it dry. **Rewrite the page.**

### Never wink at the camera

Cut "let's be honest", "quite satisfying", "honestly", "needless to say", and
every other phrase that announces a joke is happening. A joke that has to be
introduced isn't one.

### Never take a swipe at another tool

No "unlike most tools", no "the part everyone else gets wrong". It's
judgmental rather than funny, and it breaks the rule below about describing
what the software *is*.

### Never name another company for a laugh

Trademark risk, and it dates badly. Functional mentions are fine and necessary
(the tools you can import from, AI providers, identity providers), but no
brand as a punchline. "Survives being dropped down the stairs" is the move.

### Never force a wacky metaphor

Cut anything that reaches for a simile to make software seem fun. An early
draft had "without visiting each group in turn like a Victorian leaving calling
cards". It is trying, and you can hear it trying.

### Never describe the software by what it lacks

House rule, and it produces better copy anyway. Lead with what's there.

> **Wrong:** "There are no group chats."
> **Right:** "Everything here has comments on it, so the conversation about a
> thing sits on that thing, and all of it is searchable."

The absence is the consequence, never the headline.

### Never write the changelog's framing into a page

This is the one that goes wrong on every update, because updating a page
usually starts by reading the changelog, and a changelog entry is *about the
change*. A docs page is about **the software as it stands**. The reader has
never seen the old behavior and has no idea a release happened.

So when you carry a fact across, drop the version scaffolding around it:

> **Wrong:** "Deleting an account no longer destroys anything on the spot."
> **Right:** "Deleting an account hides it immediately and erases it later."
>
> **Wrong:** "Browser default follows your browser's language, which is what it
> always did."
> **Right:** "Browser default takes its cue from your browser's language."
>
> **Wrong:** "All three start where every deployment has always had them."
> **Right:** "All three start open."

The tells, and all of them are a rewrite rather than a trim: **no longer**,
**used to**, **still**, **now**, **as before**, **which is what it always did**,
**has always**, **instead of**, and any sentence whose subject is the app in a
previous release. Describe what exists; a migration state is not a state the
software is ever in for a reader arriving today.

The same goes for a tab that moved, a setting that was renamed, and a source
that was dropped. **Delete the old context, don't narrate the move.** The page
says where the thing is. If somebody genuinely needs to find their way from the
old place (a rename people have muscle memory for), that is a one-line
announcement, not a paragraph that lives on the page forever. `CLAUDE.md` has
the rules for writing one.

---

## Security and compliance pages are excluded

**Do not apply this voice** to:

- `docs/en/security/**` (including `data-and-compliance.md`,
  `private-messages.md`, `how-your-data-is-kept-separate.md`)

Somebody reading those wants a straight answer. A joke in the middle of a
retention policy helps nobody, and may end up in front of a lawyer.

Running-a-server pages **do** take the voice, but must stay operationally exact. Being
funny never costs a command its accuracy.

### And never describe an attack

Repo-wide rule, enforced here too. Say what a protection **does**, never what
would happen without it, and never name the attack it stops.

> **Wrong:** "a secure session that can't be stolen by malicious scripts — a
> common way accounts get hijacked."
> **Right:** "Your sign-in session is held in a cookie the page's own scripts
> can't read."

Grep added lines for `attacker`, `hijack`, `steal`, `exploit`, `takeover`,
`malicious`, `without this`, `would let` before committing.

---

## Structure

- **Every page needs a nav entry** in `zensical.toml`. Files and nav must match
  exactly; there is a check for this below.
- **Nav nests arbitrarily.** A group is an inline table inside the list, so a
  sub-section is `{ "Tools" = [ "en/guides/tools.md", … ] }` inside
  `"Using Initiative"`. Because `navigation.sections` is enabled, a group
  renders as a heading rather than a collapsible link, so its index page shows
  as an ordinary child rather than being absorbed into the heading.
- **Frontmatter** is an `icon:` line (Lucide, e.g. `lucide/rocket`).
- **`??? techspec`** holds detail for technical readers, usually collapsed, so
  it never interrupts the plain-language flow.
- **`!!! screenshot`** marks where an image is still needed, saying what to
  capture and where to save it.
### Tools are a defined, growing list, so treat them as one

`Tool` in `backend/app/core/tools.py` is a real enum, and it is the source of
truth for a lot of the app: role permissions, tag links, comment targets, the
frontend's `src/lib/tools.ts`, and the i18n namespace each tool owns.

Today it holds six: `project`, `document`, `queue`, `counter_group`,
`calendar`, `dashboard`.

Two rules follow, and the first one is the trap:

1. **Projects and documents are tools.** They are not a separate, more
   important category that "tools" sits beside. An early draft of
   `concepts/index.md` had three sections ("Projects and tasks", "Documents",
   and "Tools — there if you want them" listing only four), which taught the
   reader a model the app does not have. If you catch yourself writing "and
   also, tools", stop and restructure.

   Say it the way the app means it: everything inside an initiative is a tool,
   there are six kinds, two of them are where you start and four are where you
   grow. They share their sharing model, their tags, their comment threads and
   their `#` mentions, which is the actual payoff: learn one, know the rest.

2. **The list grows, so write so it can.** Avoid prose that hard-codes "the
   other four" as a permanent fact. When the enum gains a seventh, it needs a
   guide page, a nav entry under Tools, a glossary entry, and a mention
   wherever tools are enumerated (the concepts page, the tools hub, the roles
   permission table). Derive from the enum; never keep a parallel list.

Each tool has its own guide page, nested under **Tools** in the nav.
- **No emojis in prose.** They read as trying too hard.

---

## Build and check

Zensical isn't a project dependency. Install it once:

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install zensical
```

Then, from the repo root:

```bash
zensical build                      # validates links AND heading anchors
zensical serve -a 127.0.0.1:8080    # live preview with hot reload
```

Use **8080**, not the default 8000, because this checkout's backend dev server holds
8000 (see `scripts/dev-ports.sh`).

`zensical build` reports a broken cross-reference anchor as an issue, so a
clean build is a real check rather than a formality. Run it before committing.

Nav and files should agree:

```bash
python3 - <<'PY'
import re, glob
files = set(glob.glob('docs/**/*.md', recursive=True))
nav = {f"docs/{m}" for m in re.findall(r'"(en/[^"]+\.md)"', open('zensical.toml').read())}
nav.add('docs/index.md')
print("in nav, no file:", sorted(nav - files) or "none")
print("file, not in nav:", sorted(files - nav) or "none")
PY
```

---

## Before you commit

- [ ] `zensical build` reports **No issues found**.
- [ ] Nav and files agree.
- [ ] Read the page aloud. If you'd never say a sentence out loud, rewrite it.
- [ ] Cut anything that explains what the reader can see on screen. Keep the
      jokes; lose the narration.
- [ ] No winking, no swipes, no brands-as-punchlines, no wacky similes.
- [ ] Nothing describes a previous release. Grep the added lines and read
      each hit: `still` and `now` have innocent everyday senses, the rest
      rarely do:

      ```bash
      git diff -U0 -- docs/ | grep '^+' | grep -v '^+++' \
        | grep -nEi "no longer|used to|\bstill\b|as before|has always|always did|instead of"
      ```
- [ ] None of the AI tells from "Dry, not the AI version of dry". Grep the
      added lines for the ones a pattern can find:

      ```bash
      git diff -U0 -- docs/ | grep '^+' | grep -v '^+++' \
        | grep -nEi "—|also fine|still fine|\b(fete|rota|panto|allotment|colour|humour|organis\w*)\b"
      ```
- [ ] Nothing describes an attack or what breaks without a guard.
- [ ] Security and compliance pages untouched, unless that was the actual task.
- [ ] Docs-only changes go **straight to `dev`**, with no branch and no PR.
