from __future__ import annotations

from datetime import datetime
from typing import (
    Annotated,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    TYPE_CHECKING,
)

from pydantic import ConfigDict, Field, computed_field

from app.core.identity_boundary import UPLOAD_PATH
from app.schemas.base import LexicalState, SanitizedBaseModel
from app.schemas.tenant.property import PropertiesOnCreate
from app.schemas.query import PageMeta

from app.core.file_types import FileKind, FileType, spec_of
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.platform.user import UserPublic
from app.schemas.tenant.initiative import InitiativeSummary
from app.schemas.tenant.ownership import OwnerPluginSummary, owner_profile
from app.schemas.tenant.tool import ToolSummaryBase, serialize_tool

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext
    from app.models.tenant.file import File

#: One sheet of a workbook, in the canonical shape
#: ``normalize_spreadsheet_content`` produces.
SpreadsheetSheet = Dict[str, Any]


class FileBase(SanitizedBaseModel):
    name: str
    initiative_id: int
    featured_image_url: Optional[str] = None
    is_template: bool = False


class FileCreate(FileBase, PropertiesOnCreate):
    content: Optional[LexicalState] = Field(default_factory=dict)
    #: An uploaded file is made by uploading the file (``POST /files/upload``).
    file_type: Literal[
        FileType.lexical,
        FileType.excalidraw,
        FileType.url,
        FileType.sheet,
    ] = FileType.lexical
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class FileUpdate(SanitizedBaseModel):
    name: Optional[str] = None
    content: Optional[LexicalState] = None
    #: The ``content_version`` of the read this ``content`` was made from.
    #: Given and still current, the write merges in, into a live editing
    #: session too; given and out of date, it is refused with
    #: ``*_CONTENT_CHANGED``. Left out, a live session refuses the write.
    content_version: Optional[str] = None
    featured_image_url: Optional[str] = None
    is_template: Optional[bool] = None


class FileSummary(FileBase, ToolSummaryBase):
    # ``validate_by_name`` so ``derived_fields`` can set ``owner`` and
    # ``owner_plugin`` by name; their aliases keep ``from_attributes`` from reading
    # an ORM relationship.
    model_config = ConfigDict(validate_by_name=True)

    initiative: Optional[InitiativeSummary] = None
    #: The person holding the file's owner grant, or None when it is
    #: unowned or a plug-in owns it.
    owner: Optional[UserPublic] = Field(default=None, validation_alias="owner_source")
    #: The installed plug-in holding the owner grant, or None when a person owns
    #: the file or nobody does. At most one of ``owner`` and this is set.
    owner_plugin: Optional[OwnerPluginSummary] = Field(
        default=None, validation_alias="owner_plugin_source"
    )
    #: ``FileBase``'s, marked here: a request takes it as it is.
    featured_image_url: Annotated[Optional[str], UPLOAD_PATH] = None
    comment_count: int = 0
    file_type: FileType = FileType.lexical
    # Uploaded file fields, read from its current version
    file_url: Annotated[Optional[str], UPLOAD_PATH] = None
    file_content_type: Optional[str] = None
    file_size: Optional[int] = None
    original_filename: Optional[str] = None
    #: A smaller picture of an uploaded picture, for a card; ``None`` until
    #: the app has drawn it, and for every other type.
    thumbnail_url: Annotated[Optional[str], UPLOAD_PATH] = None
    #: An uploaded picture's size in pixels, turned upright; ``None`` until
    #: the app has drawn its thumbnail, and for every other type.
    width: Optional[int] = None
    height: Optional[int] = None
    # Smart-link URL surfaced on the summary so cards can render the
    # provider-specific icon without fetching the full content JSONB.
    # Only populated when file_type == "url".
    smart_link_url: Optional[str] = None

    @computed_field
    @property
    def kind(self) -> FileKind:
        """How the file is shown, which follows from its type."""
        return spec_of(self.file_type).kind

    @classmethod
    def derived_fields(
        cls, row: Any, *, context: ActorContext, user_id: Optional[int]
    ) -> dict[str, Any]:
        from app.services.tenant.ownership import owner_plugin_of

        version = row.current_version
        return {
            "owner": owner_profile(row),
            "owner_plugin": owner_plugin_of(row),
            "smart_link_url": smart_link_url(row),
            **{name: getattr(version, name, None) for name in _FILE_FIELDS},
        }


#: What a file reports of its current version.
_FILE_FIELDS = (
    "file_url",
    "file_content_type",
    "file_size",
    "original_filename",
    "thumbnail_url",
    "width",
    "height",
)


class FileListResponse(PageMeta):
    items: List[FileSummary]


class FileRead(FileSummary):
    content: LexicalState = Field(default_factory=dict)
    #: The collections it is in that the reader can see.
    collection_ids: List[int] = Field(default_factory=list)
    #: The version of ``content`` this read returns. Send it back with a
    #: ``PATCH`` of ``content`` so the write merges into the body only if
    #: nobody has changed it since. ``null`` when the body was left out.
    content_version: Optional[str] = None

    @computed_field
    @property
    def converts_to(self) -> Optional[FileType]:
        """The editor's own type this uploaded file becomes when somebody
        converts it to edit it (``POST /files/{id}/convert``), or ``None``."""
        return spec_of(self.file_type).converts_to


class FileVersionRead(SanitizedBaseModel):
    """A single stored version of an uploaded file. The binary is fetched
    via the version download endpoint by id — ``file_url`` is intentionally
    not exposed."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    version_number: int
    file_content_type: Optional[str] = None
    file_size: Optional[int] = None
    original_filename: Optional[str] = None
    #: ``null`` for a version a plug-in acting as its community uploaded.
    created_by: Optional[int] = None
    created_at: datetime
    is_current: bool = False


def smart_link_url(file: Any) -> Optional[str]:
    """The address a link file points at, so a card can draw its provider's
    mark without the content: ``File.smart_link_url``, read in the row's
    own SELECT."""
    return file.smart_link_url or None


def serialize_file(
    file: "File",
    *,
    context: ActorContext,
    user_id: Optional[int] = None,
    include_content: bool = True,
) -> FileRead:
    """The full file. ``include_content=False`` leaves the body out — every
    other field is unchanged, including the smart-link URL that is derived from
    it."""
    return serialize_tool(
        FileRead,
        file,
        context=context,
        user_id=user_id,
        **({} if include_content else {"content": {}}),
    )


class SpreadsheetImportRead(SanitizedBaseModel):
    """The sheets a file held, ready to be added to a workbook.

    Nothing is written by the read that produces this: the editor adds these
    to its live document itself, in one transaction, so an import is one thing
    to undo.
    """

    sheets: List[SpreadsheetSheet] = Field(default_factory=list)
