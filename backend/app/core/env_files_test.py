"""Tests for finding the .env files a checkout reads."""

from app.core.env_files import main_checkout


def test_a_linked_worktree_finds_its_main_checkout(tmp_path):
    main = tmp_path / "initiative"
    linked = tmp_path / "initiative-wt" / "feature"
    (main / ".git" / "worktrees" / "feature").mkdir(parents=True)
    linked.mkdir(parents=True)
    (linked / ".git").write_text(f"gitdir: {main}/.git/worktrees/feature\n")
    assert main_checkout(linked) == main.resolve()
    (linked / ".git").write_text("gitdir: ../../initiative/.git/worktrees/feature\n")
    assert main_checkout(linked) == main.resolve()
    assert main_checkout(main) == main
