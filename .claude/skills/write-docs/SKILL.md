---
name: write-docs
description: Write or edit the Initiative help center under docs/en/: the four kinds of page (front door, walkthrough, technical, reference) and the depth each needs, the house voice, the structural rules, and how to build and check the site. Use when adding a docs page, rewriting one, documenting a new feature, or when the user says docs read dry, corporate, or off-brand.
user-invocable: true
---

# /write-docs: writing the Initiative help center

The docs live in `docs/en/`, are built with [Zensical](https://zensical.org/),
and are navigated by an explicit `nav` list in `zensical.toml`.

Start by deciding which kind of page you're writing: the depth, the tone and
how long it may run all follow from that. Most of the rest is about **voice**,
because that's the part that keeps going wrong. The structural rules are at
the bottom and are short.

---

## Know which kind of page you're writing

The help center holds four kinds of page, each written for a different reader.
Decide which one you're on before you write anything, because what makes one
kind work makes another fail. A front page that walks through settings
overwhelms somebody who arrived a minute ago, and a server page written like
the front page leaves an operator guessing.

| Kind | Pages | Reader | Done when |
|---|---|---|---|
| **Front door** | `index.md`, `self-host-or-hosted.md`, `concepts/index.md`, each section's `index.md` | Just arrived; deciding whether this is for them, or where to go | They know what it is and which page to open next |
| **Walkthrough** | the rest of `getting-started/`, `guides/`, `sharing/` and `account/` | Doing a job in the app; not technical | Every job the page covers can be finished from the page alone |
| **Technical** | the rest of `running-a-server/` and `security/`, and every `??? techspec` block | An operator, a developer, an evaluator, a compliance reviewer | Nothing they need is left to guesswork or to the source code |
| **Reference** | `faq.md`, `reference/` | Looking one thing up | Each entry answers its question on its own |

A technical section's `index.md` is a front door in that section's tone. A page
can hold more than one kind: a walkthrough carries `??? techspec` blocks for
the technical reader, and a server page opens with a plain sentence or two
before the detail. Write each part for its own reader.

**Whatever the kind, it sounds like a person wrote it**: human, relatable,
brief, and funny wherever it can be. The kind decides how deep a page goes and
how often it jokes, never whether it sounds like a person. A page in AI voice
is wrong on every kind, technical ones included (see "Dry, not the AI version
of dry").

### Front door: orient, then point onward

- Say what Initiative (or this section) is, who it's for and where to go next,
  then stop.
- No steps, settings or edge cases. A newcomer who meets roles, permissions and
  plug-ins on the first screen decides the app is complicated before they've
  opened it.
- The voice is at its fullest here. Reassurance and jokes are the job.
- "Keep it brief" applies in full.

### Walkthrough: every job, every step, in plain words

Initiative is an advanced tool, and plenty of what people do in it takes
several screens: making roles for an initiative, sharing one project with
somebody outside it, giving a task type its own fields, laying out a list.
These pages walk the reader through each of those jobs completely, in everyday
language. Help for advanced work-tracking software usually walks through every
job too, but it assumes the reader already speaks its language (workflows,
schemes, fields, permissions). Ours doesn't, and shouldn't have to learn it
from a glossary first.

- **Complete.** Every job a person can do in this part of the app has a
  walkthrough, from where they'd start (which screen, which button) to the
  result. A job the app offers that no page walks through is a gap in the
  docs. Never leave out a step because it seems obvious; leave out only the
  explanation of what a visible control does.
- **Numbered steps** for any job of more than one action, one action to a
  step. Name each control in **bold**, spelled as the app spells it: the
  English strings are in `frontend/public/locales/en/*.json`, so check there
  rather than from memory.
- **A step is the action and nothing more.** "Select **Save**", not "Click
  the **Save** button to save your changes."
- **Before the steps**, in a sentence or two, say who can do it, what to do
  when they can't (the button isn't there, so who to ask), and anything they
  need first.
- **After the steps**, in a sentence, say what changed and who notices: who's
  notified, who can now see it, where it shows up.
- **No scaffold.** Don't give every job the same set of headings ("Before you
  start", "Steps", "What happens next", "Troubleshooting"). A page where every
  section has the same skeleton reads as generated, because it was.
- **Everyday words in your own sentences.** Explain a product word
  (initiative, role, layout, tool) in a clause the first time a page uses it,
  or link it to the page that owns it. Never an implementation word: entity,
  resource, instance, schema, scope, tenant. The app's own labels stay as the
  app spells them.
- **Name headings for the job**, in the words somebody would type: "Share a
  project with one person outside the initiative". The app's Help panel
  searches the help center by its headings (down to `###`), so a heading named
  for the job is how a stuck person finds it.
- **Length follows the jobs.** Keep every sentence and step short, but a page
  is as long as its jobs need. When a page covers jobs that don't belong
  together, split it.
- **Voice around the steps, never in them.** Reassure before a step that looks
  risky, and joke in the opening or between jobs. The steps are where a nervous
  reader is concentrating.

### Technical: immense detail, exactly right

This reader wants everything, stated precisely, and anything else slows them
down.

- **Exhaustive.** Every setting gets its exact name, accepted values, default,
  unit, what it changes, what happens when it's missing or wrong, and whether
  it needs a restart. Every command can be pasted and run as written. Limits,
  timeouts and versions are numbers.
- **Exact over friendly.** "After a few minutes" is wrong where the code says
  300 seconds. Take each fact from the code that sets it
  (`backend/app/core/config.py`, `docker-compose.example.yml`, the
  `Dockerfile`), not from another page.
- **Tables and code blocks** carry most of it; prose connects them.
- **No page-length limit, but every sentence is short.** Precision is the
  point; headings keep a long page navigable.
- **Still a person talking.** Plain words all the way down, the way a
  colleague who runs the thing would explain it. A dry aside belongs wherever
  it costs no precision, most often in the opening. Security pages take no
  jokes (see below).

### Reference: one question, one entry

Each entry stands alone, stays short, and answers the question its heading
asks. Reference pages are looked up, never read start to finish, so their total
length costs nothing.

---

## The front-door and walkthrough reader

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

The developer skimming for an API signature is real too, and the technical
pages are theirs. On these pages, ours wants a friendly human who knows the
software.

---

## The voice

Every page sounds like a person wrote it. The front door and the walkthroughs
take this voice in full, a technical page keeps it plain and jokes where that
costs no precision, and security pages are plain with no jokes. The AI tells
under "Dry, not the AI version of dry" are banned everywhere.

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

These are the habits that make copy read as written by an AI, and the owner
has rejected every one. The site still carries plenty of them (hundreds of em
dashes), so fix the ones on any page you touch:

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
- **No stock phrases.** "Simply", "seamlessly", "easily", "robust",
  "leverage", "ensure", "navigate to", "in order to", "this allows you to",
  "note that", "it's important to", "feel free to", "whether you're X or Y",
  "here's how". Say what you'd say out loud to a friend.
- **No essay headings or wrap-ups.** No "Overview", "Key features" or
  "Conclusion", and no closing paragraph that sums up the page. Name a heading
  for what's under it, and end the page when its last job is done.

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

Nobody reads a wall of text, our reader least of all. A front-door page that
sprawls gets closed, and so does a walkthrough whose steps ramble.

Brevity is about sentences and explanation, never coverage. It never cuts a
step from a walkthrough or a fact from a technical page.

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
The screen doesn't need narrating back to them. In a walkthrough, trusting the
software means not explaining what a visible control does; it never means
leaving out the step that uses it.

Beyond the steps, spend words on the **non-obvious**: the thing that catches
people out, the reason behind a design choice, the setting whose name doesn't
quite say what it does. Skip explaining what the interface already makes plain.

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
- A front-door page stays short enough to read whole. A walkthrough or
  technical page past roughly 1,200 words may well need the room; check that
  it isn't two pages, and that the length is steps and facts rather than
  padding.

### Don't restate a definition that already has a home

A definition copied onto a second page says it less well, with less context,
and drifts silently from the page that owns it. So the glossary holds only the
words where the everyday meaning **misleads**, such as community, initiative,
or archive vs. trash. A reader can't guess those. They can guess "subtask".

Same test anywhere else: if a page is explaining something another page owns,
link to it instead.

---

## Never do these

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

Cut anything that reaches for a simile to make software seem fun, like
"without visiting each group in turn like a Victorian leaving calling cards".
It is trying, and you can hear it trying.

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

## Security and compliance pages take no jokes

**No jokes** on:

- `docs/en/security/**` (including `data-and-compliance.md`,
  `private-messages.md`, `how-your-data-is-kept-separate.md`)

Somebody reading those wants a straight answer, in plain sentences a person
would say. A joke in the middle of a retention policy helps nobody, and may
end up in front of a lawyer.

Running-a-server pages are technical pages (see "Know which kind of page
you're writing"): human and brief, with a joke where it fits. Being funny
never costs a command its accuracy.

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
- **An FAQ question is a `###` heading** under its topic's `##`, its answer
  plain paragraphs beneath, never a collapsible block: the app's Help panel
  searches the help center by heading.
- **`!!! screenshot`** marks where an image is still needed, saying what to
  capture and where to save it.
- **Pictures are taken by script.** Each is a shot in
  `frontend/e2e/shots/help/` calling `shootHelp`, which saves a light and a
  dark `.webp`; the page shows both, with `#only-light` and `#only-dark`.
  `running-a-server/maintaining-these-docs.md` has the details.
- **A screenshot shows the app as it stands.** One showing a screen, button or
  tool the app no longer has misleads worse than no picture. When you edit a
  page, check each of its pictures against the app; retake the shots
  (`pnpm screenshots e2e/shots/help`) after a change to the screens they show,
  and remove a picture whose screen is gone.
- **No emojis in prose.** They read as trying too hard.

### Tools are a defined, growing list

`Tool` in `backend/app/core/tools.py` is a real enum, and it is the source of
truth for a lot of the app: role permissions, tag links, comment targets, the
frontend's `src/lib/tools.ts`, and the i18n namespace each tool owns. Read it
for the current list rather than counting from memory or from a page, and
don't write a count or "the other four" into a page: it drifts the day a tool
is added or removed.

When the enum gains a tool, it needs a guide page nested under **Tools** in
the nav, a glossary entry, and a mention wherever tools are enumerated (the
concepts page, the tools hub, the roles permission table).

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
- [ ] You know which kind the page is, and it does that kind's job: the front
      door points onward, a walkthrough finishes every job it covers, a
      technical page leaves nothing to guess.
- [ ] Every bold control name matches `frontend/public/locales/en/*.json`.
- [ ] Every picture on the page matches the app as it stands.
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
      git diff -U0 -- docs/ | grep '^+' | grep -v '^+++' \
        | grep -nEi "simply|seamless|easily|robust|leverag|\bensure|navigate to|in order to|allows? you to|note that|it's important|feel free|whether you're|here's how|overview|in summary|conclusion"
      ```
- [ ] Nothing describes an attack or what breaks without a guard.
- [ ] Security and compliance pages untouched, unless that was the actual task.
- [ ] Docs-only changes go through a pull request into `dev`, like every
      other change.
