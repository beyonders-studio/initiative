"""The field registry and the query vocabulary, as a client reads them.

One declaration serves the filter engine and the controls that build a filter,
so the operators a control offers cannot drift from the ones the server accepts.

Deliberately not guild-scoped: the answer describes the shape of a dataset, not
anybody's rows, and is identical for every guild on a deployment. Authentication
is still required — the field vocabulary is not something an anonymous caller
needs — but no guild context is taken, because taking one would imply the answer
depended on it.

It takes **no session** either, for the same reason: it reads nothing from the
database. The rule that an authenticated platform read runs under
``UserSessionDep`` exists so that rows come back scoped to the caller's tier,
and there are no rows here — the answer is assembled from the registry in
memory. Anything added here that *does* read the database needs that session.
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_active_user
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
from app.services.fields.registry import DatasetName, dataset_names
from app.services.query.resolve import ALLOWED_FUNCTIONS, SHEET, VIEWER

router = APIRouter()


@router.get(
    "/fields/{dataset}",
    response_model=FieldCatalogResponse,
    dependencies=[Depends(get_current_active_user)],
)
def read_field_catalog(dataset: DatasetName) -> FieldCatalogResponse:
    """The fields *dataset* offers, in the order a client lists them.

    ``dataset`` is the registry's own enum, so an unknown name is refused by
    validation rather than by a branch here that would have to be kept in step
    with the registry.
    """
    return FieldCatalogResponse(
        dataset=dataset.value,
        fields=[
            FieldDescription(**entry)
            for entry in fields_registry.describe(
                fields_registry.dataset(dataset.value)
            )
        ],
        relations=[
            RelationDescription(name=relation.name, dataset=relation.dataset)
            for relation in fields_registry.dataset(dataset.value).relations
        ],
        default_filters=[
            DefaultFilter(**condition)
            for condition in fields_registry.default_filters(dataset.value)
        ],
        groupings=[
            GroupingDescription(**entry) for entry in describe_groupings(dataset.value)
        ],
    )


@router.get(
    "/query/vocabulary",
    response_model=QueryVocabulary,
    dependencies=[Depends(get_current_active_user)],
)
def read_query_vocabulary() -> QueryVocabulary:
    """What a statement may name and call.

    Both read from the validator's own allow-lists, so a word offered here is
    one it accepts. Beside a dataset's fields (above), this is everything a
    client needs to complete a statement somebody is writing. ``sheet`` is
    among the functions: it is called in ``FROM``, to read a spreadsheet.
    """
    return QueryVocabulary(
        datasets=sorted(dataset_names()),
        functions=sorted(ALLOWED_FUNCTIONS | {SHEET}),
        tokens=[VIEWER],
    )
