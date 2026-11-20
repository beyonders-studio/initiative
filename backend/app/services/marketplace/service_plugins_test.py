"""Listing content is data here, and this is the test that keeps it that way.

A service plug-in ships ``module_source``: the JavaScript its widget renders with.
This build's only jobs are to measure it, store it, and hand it to the browser,
where it runs inside the zero-capability sandbox every widget uses. Nothing on
the server parses, compiles, imports, or evaluates it — and "nothing does" is
easy to believe and easy to lose, because it would take one convenience helper
to change.

So it is asserted structurally: every module in this package is parsed, and any
call that could turn stored text into behaviour fails this test. A new one has
to be argued for in review rather than merged quietly.

The same guard covers the rest of a manifest for the same reason — sample rows,
the automation block, and a widget's meta are all publisher-supplied text this
build stores without interpreting.
"""

import ast
from pathlib import Path

import pytest

from app.services.marketplace.definitions import normalize_listing_definition

pytestmark = pytest.mark.always


_PACKAGE = Path(__file__).resolve().parent

#: Calls that turn text into behaviour. Named rather than pattern-matched, so
#: what is banned can be read off the page.
_FORBIDDEN_CALLS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "import_module",
        "literal_eval",
        "system",
        "popen",
        "Popen",
        "check_output",
    }
)

#: The receivers allowed to own a method sharing a banned name: SQLModel spells
#: its query call ``<session>.exec()``, which has nothing to do with the
#: builtin. Named per variable rather than skipping every attribute call, so
#: ``builtins.exec(...)`` and ``obj.attr.exec(...)`` still trip the guard — a
#: new session variable adds its own line here.
_ALLOWED_METHOD_CALLS = frozenset({("session", "exec"), ("system_session", "exec")})

#: Modules whose whole purpose is running something. None of them has any
#: business on a path that handles catalog content.
_FORBIDDEN_IMPORTS = frozenset(
    {
        "subprocess",
        "importlib",
        "marshal",
        "pickle",
        "runpy",
        "ctypes",
        "code",
        "codeop",
    }
)


def _sources() -> list[Path]:
    """Every module in this package, tests excluded.

    Globbed rather than listed, so a module added here is covered the day it
    lands instead of the day someone remembers to add it.
    """
    paths = sorted(
        path for path in _PACKAGE.glob("*.py") if not path.name.endswith("_test.py")
    )
    assert paths, "no marketplace modules found to check"
    return paths


def _called_name(node: ast.Call) -> str:
    """The name a call invokes, or "" when it is allowed or unreadable.

    Attribute calls count too — a banned name is banned however it is reached —
    except for the receiver/method pairs named above.
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        receiver = func.value.id if isinstance(func.value, ast.Name) else None
        if (receiver, func.attr) in _ALLOWED_METHOD_CALLS:
            return ""
        return func.attr
    return ""


def _forbidden_calls_in(source: str, *, filename: str = "<test>") -> set[str]:
    tree = ast.parse(source, filename=filename)
    return {
        _called_name(node) for node in ast.walk(tree) if isinstance(node, ast.Call)
    } & _FORBIDDEN_CALLS


class TestNothingExecutesListingContent:
    @pytest.mark.parametrize("path", _sources(), ids=lambda path: path.name)
    def test_no_module_can_turn_text_into_behaviour(self, path):
        found = _forbidden_calls_in(
            path.read_text(encoding="utf-8"), filename=str(path)
        )
        assert not found, f"{path.name} calls {sorted(found)}"

    @pytest.mark.parametrize(
        "source",
        [
            "exec(src)",
            "eval(src)",
            "compile(src, '<s>', 'exec')",
            "__import__('os')",
            "builtins.exec(src)",
            "__builtins__.exec(src)",
            "importlib.import_module(name)",
            "ast.literal_eval(src)",
            "os.system(cmd)",
            "subprocess.check_output(cmd)",
            "obj.attr.exec(src)",
            # The SQLModel exemption is one receiver/method pair.
            "shell.exec(statement)",
        ],
    )
    def test_the_guard_catches_a_call_however_it_is_reached(self, source):
        """The allow-list is one receiver/method pair, not a blanket pass for
        attribute calls — so no spelling of these slips by."""
        assert _forbidden_calls_in(source)

    @pytest.mark.parametrize("path", _sources(), ids=lambda path: path.name)
    def test_no_module_imports_a_way_to_run_something(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        found = imported & _FORBIDDEN_IMPORTS
        assert not found, f"{path.name} imports {sorted(found)}"

    def test_a_module_that_would_be_dangerous_to_run_is_simply_stored(self):
        """The proof the guard is about something real: content that would do
        damage if it were ever executed here goes in and comes out byte for
        byte, because storing is all that happens to it."""
        source = "__import__('os').system('echo nope')\n"
        definition = normalize_listing_definition(
            "plugin",
            {
                "plugin_kind": "service",
                "service": {"public_id": "tests.widget-co"},
                "features": ["widgets"],
                "widgets": [
                    {
                        "id": "summary",
                        "meta": {"name": {"en": "Summary"}},
                        "module_source": source,
                    }
                ],
            },
        )
        assert definition["widgets"][0]["module_source"] == source
