"""The .env files the settings read, apart from the settings themselves so the
test suite can look at them before ``app.core.config`` builds its settings."""

from pathlib import Path

#: This checkout's root, the directory above backend/.
CHECKOUT = Path(__file__).resolve().parents[3]


def main_checkout(checkout: Path = CHECKOUT) -> Path:
    """The main checkout of the repository ``checkout`` is in: ``checkout`` itself,
    unless it is a linked git worktree. A worktree's ``.git`` is a file naming its
    directory under the main checkout's ``.git/worktrees/``."""
    marker = checkout / ".git"
    if not marker.is_file():
        return checkout
    gitdir = marker.read_text().strip().removeprefix("gitdir:").strip()
    worktrees = (checkout / gitdir).resolve().parent
    return worktrees.parent.parent if worktrees.name == "worktrees" else checkout


# A linked worktree reads the main checkout's backend/.env, then its own on top,
# so nothing is copied in and a worktree can still set a value of its own (OIDC
# against a local provider, say).
ENV_FILES: tuple[str | Path, ...] = (".env",)
if main_checkout() != CHECKOUT:
    ENV_FILES = (main_checkout() / "backend" / ".env", ".env")
