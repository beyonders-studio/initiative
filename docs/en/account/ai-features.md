---
icon: lucide/sparkles
---

# AI features

Initiative has optional AI help for the dull parts: drafting a task description, breaking a task into steps, summarizing a long document, catching you up on what happened while you were away, and tidying the sentence you've rewritten four times.

It's off unless somebody deliberately switches it on, and it only runs when you press a button. Nothing writes itself while you're making coffee. If you don't see the sparkle buttons below, AI isn't on in your community, and everything else in Initiative works exactly the same without it.

There's nothing for you to set up. Whoever runs your server, or your community's superadmin, picks the AI provider and pays for it; see [Who switches AI on](#who-switches-ai-on).

## Have AI draft a task's description

1. Open the task.
2. Select **AI Generate** beside the description.
3. Read what it wrote, and edit it like anything else you'd typed.

The draft goes into the description box. **Undo suggestion** puts back whatever was there before. AI writes from the whole task, not just its title: its checklist, its project, the unfinished tasks linked to it, and its comments, newest first. When a long comment thread doesn't all fit, the message after it says how many comments it read, so the draft that ignores what Priya said on Tuesday comes with a reason.

## Have AI suggest a checklist

1. Open the task.
2. Select **AI Generate** beside **Checklist**.
3. In **AI-generated checklist**, untick any step you don't want.
4. Select **Add Selected**.

Nothing is added until you select it. AI reads the task the same way as for a description, so you won't be offered "Book the hall" if it's already on the list.

## Summarize a document or wiki page

1. Open the document or wiki page.
2. Select **Summary**, the sparkle button at the top.
3. Select **Generate Summary**.

The summary writes itself in as you watch, from the page as it reads right now, including whatever a colleague typed ten seconds ago. **Copy summary** copies it, and **Regenerate summary** writes a fresh one. A very long page may not all fit; the summary then says how much of it was read. The bylaws' appendices will survive being left out.

Summaries work on documents written in Initiative. An uploaded file such as a PDF can't be summarized.

## Catch up on what changed

**Catch me up** is on your community's home page and at the top of each project.

1. Select **Catch me up**.
2. Select **Catch me up** again in the panel that opens.

You get a short summary of what changed since you were last there, reading only things you're allowed to open. It goes back a week at most, and says where it started. If nothing happened, it says so and sends nothing anywhere, which is the cheapest answer AI will ever give you.

## Get writing help in a document

In any document, wiki page or post:

1. Select the text you want help with.
2. Select the sparkle button (**Writing help**) in the toolbar above it.
3. Pick **Rewrite**, **Shorten**, **Fix spelling and grammar** or **Translate…** and a language.
4. Read the suggestion that appears under your text.
5. Select **Replace** to swap it in, **Insert below** to keep both, or **Discard**.

To have AI keep going from where your cursor is, type `/`, pick **Continue writing**, then select **Insert** or **Discard**.

Nothing in the document changes until you pick. Only your selection and the text around it are sent. If somebody else edits the same sentence while the suggestion is being written, **Replace** steps aside so it doesn't flatten their change; **Insert below** still works, and the two of you can sort it out from there.

## What gets sent to the AI provider { #the-privacy-bit-which-is-genuinely-worth-reading }

AI features work by sending text to whichever provider your community uses: a task with its comments and linked tasks, a document, the changes for Catch me up. Only things you can open yourself are ever sent. That text leaves your server and goes to that company, under its terms.

This is the one place in Initiative where your work deliberately goes somewhere else, so here it is plainly:

- **The Initiative project never trains on your content**, and has no way to. See [Why the rules are what they are](../security/data-and-compliance.md#why-the-rules-are-what-they-are).
- **What the provider does with it is between your server and that provider.** Some train on what they receive, some don't, and some let you choose. We can't promise on their behalf.

That's why every AI feature waits for a button press, and why AI can be switched off entirely.

!!! tip "Want the text to stay home?"
    Whoever runs your server can use a provider that runs on their own machine, such as Ollama or an OpenAI-compatible server like vLLM. The text never leaves your network, so there's no third party's terms to read. If your group's work is the kind you wouldn't hand a stranger, ask for this.

## Who switches AI on

Whoever runs the server chooses how AI works for the whole server, under **Platform Settings › Integrations**:

| **AI configuration mode** | What it means |
|---|---|
| **Disabled** | AI is off for everyone. |
| **Platform-managed** | The server's owner sets up the AI every community uses. |
| **Community-managed** | Each community's superadmin sets up its own, under **Community settings › Integrations**. |

It's one or the other, never both. What they set up are connections, each a provider, a model and usually a key:

| Provider | Notes |
|---|---|
| OpenAI, Anthropic, Google Gemini, DeepSeek, Groq, xAI, Together AI, OpenRouter | Hosted services. Each needs an API key from that company. |
| **OpenAI-compatible server** | Anything that speaks the OpenAI API at the address you give, up to `/v1`: vLLM, llama.cpp, LM Studio, LocalAI, or a gateway. The key is optional. |
| Ollama | Models on a machine the server owner runs. Only the server owner can add one. |

### Set up an AI connection

1. Open **Integrations** in **Platform Settings** or **Community settings**.
2. Select **Add connection**.
3. Give it a **Label**, and choose the **Provider**.
4. Fill in the **API key**, and the **Base URL** for a server of your own.
5. Type a **Model** name, or leave it for now.
6. Select **Test** to check it answers.
7. Select **Save connection**.
8. If you left the model empty, select **Edit** on the connection and pick one from the provider's list.

A connection marked **Needs a model** does nothing until somebody picks one. With several connections, members use the one ticked as **Default connection**. On a platform-managed server, the owner can give a connection to particular communities under **Communities**; they use it on its key and nobody else does, which suits a company where each department pays from its own account. When a provider starts refusing requests (out of credit, a spending limit reached, a key withdrawn), the connection says **Failing since** and why.

### Switch AI off for one community

Where your server gives a community its own security settings, its superadmin can switch AI off there alone, with **AI features** under **Community settings › Security**. Off, nothing from that community goes to any provider, whatever the server offers. The legal team's notes stay the legal team's.
