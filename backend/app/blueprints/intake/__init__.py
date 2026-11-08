"""Project blueprints: what "set this up for me" imports for each stream.

Each file here is a :class:`ProjectExportEnvelope` — the same portable shape
the export endpoint produces and ``import_project`` consumes, keyed by name and
handle rather than by id. Setting a stream up is therefore an *import*, and
what it produces is an ordinary project the team restructures however it likes.

A blueprint carries the stream's statuses, the case fields the writer fills
(``app.core.intake.STREAM_FIELDS``), and one seed task explaining how the
project is fed. ``blueprints_test`` holds the files and the registry in step.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.core.intake import IntakeStream, meta
from app.schemas.tenant.project_export import ProjectExportEnvelope

BLUEPRINT_DIR = Path(__file__).parent

#: The statuses a blueprint gives a stream that holds a conversation with
#: whoever filed a case: the one that shows them the case is waiting on them,
#: and the one their answer moves it to. Setting a stream up from its blueprint
#: names them on the binding, so its filers see "Waiting on you" from the start.
WAITING_ON_REQUESTER = "Waiting on requester"
REQUESTER_REPLIED = "Requester replied"

#: The type the Ideas blueprint gives a published idea. Setting the board up
#: names it on the binding, so a task of any other type there is a draft. No
#: project starts with a type of this name, so a task moved onto the board,
#: which keeps a type of the same name, lands as a draft.
PUBLISHED_TYPE = "Published"


@lru_cache(maxsize=None)
def blueprint_for(stream: IntakeStream) -> ProjectExportEnvelope:
    """The committed envelope that sets ``stream`` up.

    Parsed once per process and cached: the files ship with the release and
    cannot change under a running server.
    """
    path = BLUEPRINT_DIR / meta(stream).blueprint
    return ProjectExportEnvelope.model_validate(json.loads(path.read_text()))
