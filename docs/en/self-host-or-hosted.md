---
icon: lucide/split
---

# Self-host or let us host it

Initiative comes two ways, and it's the same software in both. The real difference is who has to get up at 2 a.m. when the disk fills.

<div class="grid cards" markdown>

-   :material-server: __Host it yourself__

    Free, open source and the whole product. It runs happily on a spare mini PC, a NAS or a cheap cloud server.

    [:octicons-arrow-right-24: Installation guide](running-a-server/installation.md)

-   :material-cloud-outline: __Let us host it__

    [Initiative Cloud](https://initiativetasks.com) is the paid version we run for you. You sign up, and the server becomes our problem.

</div>

## What's the same

Everything in the app is in both versions, including every protection, from the walls between communities to the encryption on private messages. Nothing is held back to make the hosted version look better.

Your data is yours either way, and you can export it, delete it or take it somewhere else. See [Data & compliance](security/data-and-compliance.md).

## What's different

| | **You host it** | **We host it** |
|---|---|---|
| Cost | Free, plus whatever the machine costs you | A paid subscription |
| Setup | A Docker Compose file that brings its own database | Sign up |
| Updates, backups, uptime | Yours | Ours |
| Where your data lives | Wherever you put it | With us |
| Who you ask when it breaks | You, and other people who run it | Us |
| Plug-ins that connect to another service | You set them up once | Already set up |

## Plug-ins that need something running behind them

Most [plug-ins](guides/plugins-and-marketplace.md) are just something new on the screen. A few connect Initiative to another service, and that connection has to be set up on the server once before anybody can use it.

On a server you run, that's your job. Connecting GitHub, for example, takes one button in Initiative and a confirmation on GitHub's side. On the hosted service it's already done. See [Running plug-ins](running-a-server/plugins.md).

## Which one is you?

**Host it yourself if** you already run things (a NAS, a homelab, a couple of containers you're weirdly fond of), or if where the data physically sits is something you personally answer for. Data residency stops being a negotiation when you're the one picking the data center.

**Let us host it if** you'd rather spend your evening on the actual work. The club treasurer and the PTA chair didn't sign up to find out what a database is, and they shouldn't have to.

You can switch later, in either direction. Exports are ordinary files, and a whole community exports as one file that another server can import. Start with the [installation guide](running-a-server/installation.md) if you're running your own, and keep [Backups & updates](running-a-server/backups-and-updates.md) handy, because those two jobs are yours.
