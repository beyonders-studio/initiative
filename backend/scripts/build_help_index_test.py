"""The Help panel's index, as the docs workflow makes it from Zensical's
``search.json``."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "build_help_index.py"


def _run(
    tmp_path: Path, index: object
) -> tuple[subprocess.CompletedProcess[str], Path]:
    source, target = tmp_path / "search.json", tmp_path / "help-index.json"
    source.write_text(json.dumps(index), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(source), str(target)],
        capture_output=True,
        text=True,
    )
    return done, target


def _item(location: str, level: int, title: str, text: str, path: list[str]) -> dict:
    return {
        "location": location,
        "level": level,
        "title": title,
        "text": text,
        "path": path,
        "tags": [],
    }


def test_it_keeps_what_the_panel_shows(tmp_path):
    long = "<p>" + "word " * 60 + "</p>"
    done, target = _run(
        tmp_path,
        {
            "config": {"lang": ["en"], "separator": "[\\s]+"},
            "items": [
                _item("", 1, "Initiative Help", "", ["Initiative Help"]),
                _item("en/faq/", 1, "Frequently asked questions", "", ["FAQ"]),
                _item("en/faq/#getting-in", 2, "Getting in", "", ["FAQ"]),
                _item(
                    "en/faq/#my-invite-link-doesnt-work",
                    3,
                    "My invite link doesn&#x27;t work",
                    "<p>Links can   expire.</p><p>Ask for a <code>&lt;fresh&gt;</code>"
                    " one.</p>",
                    ["FAQ"],
                ),
                _item("en/faq/#deeper", 4, "Deeper", "<p>x</p>", ["FAQ"]),
                _item("en/faq/#untitled", 3, "", "<p>x</p>", ["FAQ"]),
                _item("en/faq/#getting-in", 2, "Getting in", "", ["FAQ"]),
                _item(
                    "en/account/",
                    1,
                    "Account &amp; settings",
                    long,
                    ["Account & settings", "Account &amp; settings"],
                ),
            ],
        },
    )
    assert done.returncode == 0, done.stderr
    items = json.loads(target.read_text(encoding="utf-8"))["items"]
    assert items[:3] == [
        {
            "title": "Frequently asked questions",
            "section": "FAQ",
            "location": "en/faq/",
            "snippet": "",
        },
        {
            "title": "Getting in",
            "section": "FAQ",
            "location": "en/faq/#getting-in",
            "snippet": "",
        },
        {
            "title": "My invite link doesn't work",
            "section": "FAQ › Getting in",
            "location": "en/faq/#my-invite-link-doesnt-work",
            "snippet": "Links can expire. Ask for a <fresh> one.",
        },
    ]
    (account,) = items[3:]
    assert account["title"] == "Account & settings"
    assert account["section"] == ""
    assert account["snippet"].endswith("word…")
    assert len(account["snippet"]) <= 201


@pytest.mark.parametrize(
    "index",
    [
        [],
        {"config": {}},
        {
            "items": [
                {"location": "en/", "level": "1", "title": "x", "text": "", "path": []}
            ]
        },
        {"items": [_item("es/", 1, "Hola", "", ["Inicio"])]},
    ],
    ids=["not-an-object", "no-items", "wrong-field-type", "nothing-in-english"],
)
def test_an_index_it_cannot_read_stops_the_build(tmp_path, index):
    done, target = _run(tmp_path, index)
    assert done.returncode == 1
    assert "build_help_index:" in done.stderr
    assert not target.exists()
