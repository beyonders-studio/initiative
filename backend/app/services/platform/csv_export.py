import csv
import io
import re
from collections.abc import Iterable, Sequence

from app.models.platform.user import User

# UTF-8 BOM so Excel on Windows auto-detects encoding rather than falling back
# to the system code page and garbling accented characters.
_BOM = "\ufeff"

# Leading characters that spreadsheet apps (Excel, Google Sheets, LibreOffice)
# interpret as the start of a formula. Exported cells are text, so a cell
# beginning with one of these is prefixed to keep it from being evaluated.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def neutralize_cell(value: object) -> object:
    """Prefix a leading formula trigger with a single quote so spreadsheets treat
    the cell as text. Non-string and benign values are returned unchanged."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if text.startswith(_FORMULA_TRIGGERS):
        return "'" + text
    return value


def restore_cell(text: str) -> str:
    """The text a cell held before :func:`neutralize_cell` prefixed it, so a
    phone number written ``+44 …`` reads back as it was."""
    if text.startswith("'") and text[1:].startswith(_FORMULA_TRIGGERS):
        return text[1:]
    return text


def build_csv(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> bytes:
    """Serialize rows to a UTF-8 encoded CSV byte string with a BOM prefix.

    Every cell (headers included) is passed through ``neutralize_cell`` so a
    value beginning with a formula trigger opens as text in a spreadsheet
    application."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([neutralize_cell(value) for value in headers])
    for row in rows:
        writer.writerow([neutralize_cell(value) for value in row])
    return (_BOM + buffer.getvalue()).encode("utf-8")


def safe_filename_component(value: str) -> str:
    """Reduce a string to characters that are safe to embed in a download filename."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return cleaned or "export"


def format_initiative_roles(user: User) -> str:
    """Serialize a user's loaded initiative roles as 'Name: role; Name: role'."""
    roles = getattr(user, "initiative_roles", []) or []
    parts = []
    for entry in roles:
        name = getattr(entry, "initiative_name", None) or ""
        role = getattr(entry, "role", None) or ""
        parts.append(f"{name}: {role}" if role else name)
    return "; ".join(parts)
