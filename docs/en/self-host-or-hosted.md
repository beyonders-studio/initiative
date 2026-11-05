---
icon: lucide/split
---

# Self-host or let us host it

Initiative comes two ways. Same software, same protections, either way. The difference is mostly about who has to get up at 2am when the disk fills.

<div class="grid cards" markdown>

-   :material-server: __Host it yourself__

    Free, open source, and the whole thing. Runs happily on a spare mini PC, a NAS, or a cheap cloud box.

    [:octicons-arrow-right-24: Installation guide](running-a-server/installation.md)

-   :material-cloud-outline: __Let us host it__ · *coming soon*

    A paid service. You sign up, you're in, and the server becomes entirely our problem.

</div>

## What's the same

Initiative itself, entirely. There is no "community edition" here with the good bits quietly filed off.

- **Every feature in the app.** Projects, files, whiteboards, the calendar, counters, dashboards, boards, tags, the marketplace, encrypted messages. All of it, both ways.
- **Every protection.** The same isolation between groups, the same access model, the same end-to-end encryption on direct messages.
- **Your data stays yours either way.** Export it, delete it, take it somewhere else. See [Data & compliance](security/data-and-compliance.md).

Nothing in Initiative is held back to make the hosted version look better. What the hosted service adds is a couple of **separate services running alongside it** — described below — rather than features carved out of the app you'd otherwise have.

## What's different

| | **You host it** | **We host it** |
|---|---|---|
| Cost | Free (you pay for the machine) | Paid subscription |
| Setup | Docker Compose, about ten minutes | Sign up |
| Updates, backups, uptime | Yours | Ours |
| Where your data lives | Wherever you put it | Where our service runs |
| Who you ask when it breaks | You, and the community | Us |
| Version you're on | Whichever you pull | The current one |
| Plug-ins that need something set up behind them | You set it up | Already done |
| Automations | — | Available, metered separately |

### Plug-ins that need something running behind them

Some [marketplace plug-ins](guides/plugins-and-marketplace.md#adding-a-plug-in) aren't just a screen — they need something set up behind them to do their job.

On a server you run, that's yours to set up. On the hosted service it's already done. Two we're launching with:

**GitHub integration.** Connect a repository so the work in Initiative and the work in your codebase stop being two separate stories somebody has to reconcile by hand.

This one is **open source like the rest of Initiative**, and runs inside it, so there's no extra program to stand up. On your own server it needs a GitHub App of its own, which takes one button and a confirmation on GitHub. See [Running plug-ins](running-a-server/plugins.md#a-plug-in-that-runs-inside-initiative).

**Automations.** Rules that do the repetitive bit for you, so nobody has to remember to move the card every Friday. Hosted only, and priced separately from the subscription.

The actual reason, since you deserve it: automations aren't a screen we drew once. They have to be *running and listening* the whole time your rules exist, which costs us continuously — the same unglamorous way storage does — and goes up the more you use it. That's a running cost being passed along, not a feature held back to make a cheaper plan look thin.

More will follow, of both kinds.

## Which one is you?

**Host it yourself if** you already run things — a NAS, a homelab, a couple of containers you're weirdly fond of — or if where the data physically sits is something you personally have to answer for. Data residency stops being a negotiation when you're the one picking the datacentre.

**Let us host it if** you'd rather spend your evening on the actual work. A club treasurer, a small business owner, a PTA chair — none of you signed up to find out what a database is, and none of you should have to.

It's also the only route to automations.

You can start on one and move to the other, too. Same software, and the export formats are ordinary files rather than something only we can open.

!!! info "The hosted service isn't open yet"
    It's coming. Until then, self-hosting is the way in — and it's a genuinely good way in, not a consolation prize with a countdown on it. Plenty of groups will run it themselves forever and never once feel short-changed.

    Start with the [installation guide](running-a-server/installation.md).

## Related

- [Installation](running-a-server/installation.md) — get a server running.
- [Data & compliance](security/data-and-compliance.md) — ownership, residency, and what a court could actually be handed.
- [Backups & updates](running-a-server/backups-and-updates.md) — the two jobs that are yours if you self-host.
