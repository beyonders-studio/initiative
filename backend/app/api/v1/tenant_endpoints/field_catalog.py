"""The field registry and the query vocabulary, as a client reads them.

One declaration serves the filter engine and the controls that build a filter,
so the operators a control offers cannot drift from the ones the server accepts.

Addressed inside a community: the datasets a statement may name are its tool
set's, the built-in tools' and those of every tool plug-in it has installed.
The answer describes the shape of a dataset, not anybody's rows, so it reads
the tool set the seam established and takes no session of its own.
"""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import GuildContextDep
from app.core.messages import QueryMessages
from app.schemas.field_catalog import (
    DefaultFilter,
    FieldCatalogResponse,
    FieldDescription,
    GroupingDescription,
    RelationDescription,
)
from app.schemas.sql_query import QueryVocabulary
from app.services import fields as fields_registry
from app.services.fields.grouping import describe_groupings
from app.services.fields.registry import dataset_names
from app.services.query.resolve import ALLOWED_FUNCTIONS, PLUGIN, SHEET, VIEWER

router = APIRouter()


@router.get("/fields/{dataset}", response_model=FieldCatalogResponse)
def read_field_catalog(
    dataset: str, guild_context: GuildContextDep
) -> FieldCatalogResponse:
    """The fields *dataset* offers, in the order a client lists them.

    ``dataset`` is any dataset of the community's tool set; another name is
    not found.
    """
    tools = guild_context.tools
    try:
        source = fields_registry.dataset(dataset, tools)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QueryMessages.UNKNOWN_RELATION,
        ) from None
    return FieldCatalogResponse(
        dataset=dataset,
        fields=[
            FieldDescription(**entry) for entry in fields_registry.describe(source)
        ],
        relations=[
            RelationDescription(name=relation.name, dataset=relation.dataset)
            for relation in source.relations
        ],
        default_filters=[
            DefaultFilter(**condition)
            for condition in fields_registry.default_filters(dataset, tools)
        ],
        groupings=[
            GroupingDescription(**entry) for entry in describe_groupings(dataset, tools)
        ],
    )


@router.get("/query/vocabulary", response_model=QueryVocabulary)
def read_query_vocabulary(guild_context: GuildContextDep) -> QueryVocabulary:
    """What a statement in this community may name and call.

    Both read from the validator's own allow-lists, so a word offered here is
    one it accepts. Beside a dataset's fields (above), this is everything a
    client needs to complete a statement somebody is writing. ``sheet`` is
    among the functions: it is called in ``FROM``, to read a spreadsheet.
    """
    return QueryVocabulary(
        datasets=sorted(dataset_names(guild_context.tools)),
        functions=sorted(ALLOWED_FUNCTIONS | {SHEET, PLUGIN}),
        tokens=[VIEWER],
    )
