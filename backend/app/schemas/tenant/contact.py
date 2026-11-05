"""A contact as the API carries it: a person or an organization, and how to
reach them."""

from __future__ import annotations

from typing import Any, List, Optional
from urllib.parse import urlsplit

from pydantic import EmailStr, Field, field_validator

from app.core.messages import ContactMessages
from app.schemas.base import SanitizedBaseModel, TitleStr, reject_null
from app.schemas.query import PageMeta
from app.schemas.tenant.property import PropertiesOnCreate
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.tool import ToolSummaryBase

#: The longest label a detail takes: "Office", "Mobile", "Billing".
LABEL_MAX_LENGTH = 40
#: How many of each detail one contact holds.
MAX_DETAILS = 20
#: What a phone number may be written with: digits, the marks people group
#: them by, a leading plus, and an ``x`` before an extension.
PHONE_CHARACTERS = frozenset("0123456789 +-().xX")


class ContactDetail(SanitizedBaseModel):
    """One of a contact's details: its value, and a short label saying which
    one it is."""

    label: str = Field(default="", max_length=LABEL_MAX_LENGTH)
    value: str = Field(min_length=1, max_length=1000)

    @field_validator("label", "value", mode="before")
    @classmethod
    def _trimmed(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class ContactEmail(ContactDetail):
    value: EmailStr


class ContactPhone(ContactDetail):
    value: str = Field(min_length=1, max_length=40)

    @field_validator("value")
    @classmethod
    def _dialable(cls, value: str) -> str:
        if not set(value) <= PHONE_CHARACTERS or not any(c.isdigit() for c in value):
            raise ValueError(ContactMessages.PHONE_INVALID)
        return value


class ContactAddress(ContactDetail):
    """An address, as one block of text written as it is on an envelope, so
    any country's form fits."""


class ContactWebsite(ContactDetail):
    value: str = Field(min_length=1, max_length=2048)

    @field_validator("value")
    @classmethod
    def _web_address(cls, value: str) -> str:
        """An http or https address; one written without a scheme is https."""
        address = value if "://" in value else f"https://{value}"
        try:
            parts = urlsplit(address)
            parts.port  # a port that is not a number raises
        except ValueError:
            raise ValueError(ContactMessages.WEBSITE_INVALID) from None
        if (
            parts.scheme.lower() not in ("http", "https")
            or not parts.hostname
            or any(c.isspace() for c in address)
        ):
            raise ValueError(ContactMessages.WEBSITE_INVALID)
        return address


class ContactCreate(PropertiesOnCreate):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    is_organization: bool = False
    #: Several of each, in the order they are shown; the first is the one a
    #: table shows.
    emails: List[ContactEmail] = Field(default_factory=list, max_length=MAX_DETAILS)
    phones: List[ContactPhone] = Field(default_factory=list, max_length=MAX_DETAILS)
    addresses: List[ContactAddress] = Field(
        default_factory=list, max_length=MAX_DETAILS
    )
    websites: List[ContactWebsite] = Field(default_factory=list, max_length=MAX_DETAILS)
    #: Which initiative the contact belongs to, or ``None`` for one of the
    #: community's contacts, which the community contacts plug-in holds.
    initiative_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # Defaults to Viewer for all initiative members, which at community scope
    # reads as every member of the community.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class ContactUpdate(SanitizedBaseModel):
    """A change to a contact. Only what is sent is written; a list sent
    replaces the one there."""

    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    is_organization: Optional[bool] = None
    emails: Optional[List[ContactEmail]] = Field(default=None, max_length=MAX_DETAILS)
    phones: Optional[List[ContactPhone]] = Field(default=None, max_length=MAX_DETAILS)
    addresses: Optional[List[ContactAddress]] = Field(
        default=None, max_length=MAX_DETAILS
    )
    websites: Optional[List[ContactWebsite]] = Field(
        default=None, max_length=MAX_DETAILS
    )

    _required = reject_null(
        "name", "is_organization", "emails", "phones", "addresses", "websites"
    )


class ContactSummary(ToolSummaryBase):
    #: NULL on a community contact.
    initiative_id: Optional[int] = None
    name: str
    is_organization: bool = False
    emails: List[ContactDetail] = Field(default_factory=list)
    phones: List[ContactDetail] = Field(default_factory=list)
    addresses: List[ContactDetail] = Field(default_factory=list)
    websites: List[ContactDetail] = Field(default_factory=list)


class ContactRead(ContactSummary):
    pass


class ContactListResponse(PageMeta):
    items: List[ContactSummary]
