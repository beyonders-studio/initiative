---
icon: lucide/users-round
---

# Sharing & access

"Who can see this?" is the question everything else in a shared tool hangs off, and the one people worry about most.

Initiative answers it in **layers**, from the outside in. Each layer narrows the one before it, so the people who end up seeing a thing are exactly the people you put in front of it — not a soul more.

## The simple version

To reach something, you have to clear each gate in turn:

```mermaid
graph LR
  A["In the community?"] --> B["In the initiative?"]
  B --> C["Does your role<br/>allow this tool?"]
  C --> D["Is this item<br/>shared with you?"]
  D --> E["Access"]
```

1. **Are you in the community?** If not, you see nothing in it. Full stop, end of conversation.
2. **Are you in the initiative?** Even inside a community, an initiative is only visible to the people added to it. This is the big one — it's how a business keeps payroll planning away from seasonal staff, and how the spring play team keeps its work away from the summer show team, in the same workspace.
3. **Does your role allow this kind of thing?** Your [initiative role](initiative-roles.md) decides which *tools* you can use — whether you can make projects, or only look at them.
4. **Is this particular item shared with you?** Each project and file can be shared with specific people or roles, at **view**, **edit**, or **own**. See [Sharing projects & files](sharing-projects-and-files.md).

All four have to be true.

Which sounds like a lot to keep track of, and here's the good news: you don't have to. In practice it's just "join a group, join an effort, get a role, have things shared with you." The gates do the worrying so you don't have to.

## Two deliberate exceptions

Two kinds of person see more than the layers above suggest, on purpose:

- **Community administrators** always see and manage everything in *their own* community. Somebody has to be able to keep the lights on and find the thing that's gone missing.
- **Support staff** (on a hosted service) can be granted **temporary, time-limited, recorded** access to help with a problem. Granted explicitly, expires on its own, logged the whole time. See [Security & privacy](../security/index.md).

## Why a missing thing says "not found" rather than "denied"

If you're not in an initiative, its projects and files aren't locked doors you can rattle. They simply aren't there for you.

A direct link comes back "not found" rather than "access denied", because as far as your account is concerned there is genuinely nothing at that address. Nobody has to be told they're excluded from something, and nobody learns that a thing exists by bumping into a wall.

Inside an initiative you *are* in, it's friendlier. A link to something there that wasn't shared with you says **You need access**, and offers to ask whoever owns it. You learn that it exists, and nothing else: not its name, not who made it. See [Asking for access](sharing-projects-and-files.md#asking-for-access).

## In this section

<div class="grid cards" markdown>

-   :material-shield-account-outline: __Initiative roles__

    What roles are, what they unlock, and the Moderator role's all-access pass.

    [:octicons-arrow-right-24: Initiative roles](initiative-roles.md)

-   :material-share-variant-outline: __Sharing projects & files__

    Share with people or whole roles, at view / edit / own.

    [:octicons-arrow-right-24: Sharing projects & files](sharing-projects-and-files.md)

-   :material-account-clock-outline: __Guests__

    Let somebody in for a set number of days, to just the initiatives and items they need.

    [:octicons-arrow-right-24: Guests](guests.md)

</div>

??? techspec "For the technically minded — where these layers are enforced"
    Not in interface logic. The community boundary is structural — a separate database schema per community, which a request is routed into and cannot reach outside of. The initiative boundary, role checks and item-level sharing are enforced inside that schema by the database's own row-level security, evaluated on every statement, so the database has the final say rather than the application. Full architecture, including the audited support-access path, in [How your data is kept separate](../security/how-your-data-is-kept-separate.md).
