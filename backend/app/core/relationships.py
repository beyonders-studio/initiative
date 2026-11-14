"""How two things connect — the vocabulary of edges, declared once.

A relationship is ``source -> relationship_type -> target`` between any two
addressable things in a guild. This module owns three declarations and nothing
else:

* :class:`RelationshipType` — the primitives, each with a fixed reading;
* :class:`RelationshipSpec` — what is TRUE of each one, in the standard
  vocabulary of binary relations;
* :data:`ENDPOINT_KINDS` — what may sit on either end, and how a ``(kind,
  id)`` pair becomes one integer (the permanent codes are the kinds' own, in
  :data:`app.core.tools.KINDS`), and :data:`PERSON`, the one end that is not a
  kind.

It is dependency-free (no models, no SQLAlchemy) so ``app.db``'s registry layer
can import it alongside :mod:`app.core.tools`, the same way
:mod:`app.core.reactions` is imported.

What is deliberately NOT here: any statement about who may write an edge. That
falls out of what the edge describes — see :class:`RelationshipSpec`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.core.references import REFERENCEABLE_TYPES
from app.core.search import SearchEntityType
from app.core.tools import KINDS, Kind


class RelationshipType(str, Enum):
    """The primitives. Small, stable, and each one carries a rule or a weight.

    A member earns its place by something depending on telling it apart from
    its neighbours — a read, a rule, an adjacency weight — not by a model being
    able to learn it. Finer words that obey an existing primitive's rule are
    :data:`SUBTYPES`, not members here: splitting a primitive later is
    impossible, because the fact that would distinguish the halves was never
    recorded, while merging two is one UPDATE.
    """

    #: A project and a file placed together. Symmetric: it describes the
    #: pair, not either end.
    attached = "attached"
    #: X cannot proceed until Y. Precedence.
    depends_on = "depends_on"
    #: X is a piece of Y. Composition — a different fact from precedence, and
    #: they predict different things.
    part_of = "part_of"
    #: X carries the label Y. Directional: a tag is a label, so the edge
    #: describes the thing carrying it.
    tagged_with = "tagged_with"
    #: X's own words name Y. Directional, and the only primitive nobody asserts
    #: by hand: it is read out of a body on save and withdrawn the same way.
    #: Two things naming each other is ordinary rather than contradictory, which
    #: is why this is not asymmetric.
    references = "references"
    #: These belong together and there is no better word for it.
    related_to = "related_to"


@dataclass(frozen=True)
class RelationshipSpec:
    """What is true of this relation. Nothing else.

    These are the standard **property characteristics** of a binary relation —
    the algebra of relations, which OWL spells ``SymmetricProperty`` /
    ``TransitiveProperty`` / ``AsymmetricProperty``. Standard names mean the
    semantics need no explaining, and each one drives a specific derivation:

    ``symmetric``
        The row is stored once, in node-id order, and a write asks only READ on
        both ends — a relation that describes neither endpoint modifies
        neither.
    ``transitive``
        A walk past one hop is meaningful. Walking a non-transitive relation to
        depth N returns nonsense that reads like a result, so the service
        refuses it.
    ``asymmetric``
        An observed 2-cycle is a contradiction, which is what makes it
        *detectable*. Note this is declared **intent**, not a constraint: the
        table records the contradiction anyway, because two people saying
        neither of two tasks can go first is the strongest coupling evidence
        the system will ever get.

    There is deliberately **no authorization field**. Direction is chosen so
    the source is the end the edge describes, which makes who-may-write
    derivable: write on the source and read on the target, or — where there is
    no described end — read on both.
    """

    symmetric: bool = False
    transitive: bool = False
    asymmetric: bool = False


#: What is true of each primitive. The RLS renderer, the walk endpoint and the
#: service all read this rather than restating any of it.
SPECS: dict[RelationshipType, RelationshipSpec] = {
    RelationshipType.attached: RelationshipSpec(symmetric=True),
    RelationshipType.depends_on: RelationshipSpec(transitive=True, asymmetric=True),
    RelationshipType.part_of: RelationshipSpec(transitive=True, asymmetric=True),
    RelationshipType.tagged_with: RelationshipSpec(asymmetric=True),
    RelationshipType.references: RelationshipSpec(),
    RelationshipType.related_to: RelationshipSpec(symmetric=True),
}

#: Types stored once per unordered pair, in node-id order.
SYMMETRIC_TYPES: frozenset[RelationshipType] = frozenset(
    t for t, spec in SPECS.items() if spec.symmetric
)

#: Types nobody asserts by hand. They are read out of a body when it is saved
#: and withdrawn when it is edited, so the manual surface neither makes one nor
#: takes one back — editing the sentence is how you do both.
DERIVED_TYPES: frozenset[RelationshipType] = frozenset({RelationshipType.references})

#: What each primitive is called when a change to it is reported against the
#: thing it describes — the label an outbox event carries in ``changed``.
#:
#: The name comes from the PRIMITIVE rather than from the table, which is what
#: lets storage move without a subscriber noticing: a junction named
#: ``task_tags`` derived ``tags`` from its own name, and a ``tagged_with`` edge
#: says ``tags`` because that is what the relation is, wherever it is kept.
FACETS: dict[RelationshipType, str] = {
    RelationshipType.attached: "attachments",
    RelationshipType.depends_on: "dependencies",
    RelationshipType.part_of: "parts",
    RelationshipType.tagged_with: "tags",
    RelationshipType.references: "references",
    RelationshipType.related_to: "relationships",
}


#: Finer words for an edge that obeys its primitive's rule — ``impeded_by``
#: under ``depends_on``, ``uses`` under ``attached``. A subtype is a word the UI
#: may show and a feature a scorer may read; rules, adjacency weights and the
#: RLS legs read the PRIMITIVE only, so this can grow forever without ever
#: re-partitioning the primitive pool.
#:
#: Ships EMPTY. The column exists from the first release so the API and read
#: schemas do not move later; the first member lands when a surface asks for it.
SUBTYPES: dict[str, RelationshipType] = {}


class Provenance(str, Enum):
    """How we know about an edge — orthogonal to what it means.

    Not decoration: it is the sample weight any future scoring reads, and it
    decides whether a removal is worth remembering. A person taking a link back
    is a deliberate negative; a link vanishing because somebody edited the
    sentence that implied it asserts nothing.

    Server-assigned per code path, never taken from a request.
    """

    #: A person, through the API.
    manual = "manual"
    #: The save path, from a reference in a body.
    content = "content"
    #: A person accepting a suggestion. Nothing writes this but the accept path.
    inferred = "inferred"


PROVENANCES: tuple[Provenance, ...] = tuple(Provenance)


#: The kinds that may sit on either end of an edge, keyed by kind. Derived from
#: ``REFERENCEABLE_TYPES`` — if a reference can name it, an edge can too, and
#: the resolvers a reference already needs are the ones an endpoint needs. A
#: person may sit on an end too (:data:`PERSON`), and has no table here.
ENDPOINT_KINDS: dict[SearchEntityType, Kind] = {
    kind: KINDS[kind.value] for kind in REFERENCEABLE_TYPES
}

#: A person on one end of an edge: a member's account, ``users.id``. Not one of
#: :data:`~app.core.tools.KINDS`, which is what a reference names and search
#: finds, and a person is neither; it takes its permanent code from the same
#: sequence. The end that is not an item asks nothing of a reader, as a tag's
#: does: an edge to a person is read and written through the item on its other
#: end.
PERSON = Kind("user", 18)

#: Everything that may sit on either end, as the API names it: the kinds, and
#: the person.
EndpointKind = Enum(
    "EndpointKind",
    {v: v for v in sorted([*(kind.value for kind in ENDPOINT_KINDS), PERSON.value])},
    type=str,
    module=__name__,
)

#: The CHECK constraint's vocabulary, in a stable order.
ENDPOINT_KIND_VALUES: tuple[str, ...] = tuple(kind.value for kind in EndpointKind)

#: Each end's permanent code, by its name.
_CODES: dict[str, int] = {
    **{kind.value: endpoint.code for kind, endpoint in ENDPOINT_KINDS.items()},
    PERSON.value: PERSON.code,
}

#: How many low bits of a node id hold the entity id. Entity ids are ``int4``,
#: so 31 bits are in use and 32 is the natural boundary; the kind code occupies
#: the bits above. 16 kinds need 5 bits, leaving a bigint's remaining range
#: spare for both to grow.
NODE_ID_SHIFT = 32


def node_id(kind: EndpointKind, entity_id: int) -> int:
    """One integer addressing one thing, derived rather than registered.

    Every graph algorithm — a recursive walk, a component pass, anything
    off-the-shelf — addresses nodes as integers, and ours are ``(kind, id)``
    pairs. Packing the pair is reversible and needs nothing stored, where a
    registry table would be a second source of truth written on every entity
    insert and able to drift.

    The database computes the same value in a generated column, so SQL and
    Python agree by construction rather than by convention.
    """
    return node_base(kind) | entity_id


def node_base(kind: EndpointKind) -> int:
    """The high half of every node id of one kind.

    What a SQL expression adds an id column to, so a query can ask the indexed
    ``*_node`` column about a whole table's worth of rows without the database
    having to see through a two-column encoding it has no index for.
    """
    return _CODES[kind.value] << NODE_ID_SHIFT


def decode_node_id(value: int) -> tuple[EndpointKind, int]:
    """``node_id`` backwards: the kind and the id it was built from."""
    code = value >> NODE_ID_SHIFT
    entity_id = value & ((1 << NODE_ID_SHIFT) - 1)
    for kind, kind_code in _CODES.items():
        if kind_code == code:
            return EndpointKind(kind), entity_id
    raise ValueError(f"no endpoint kind has code {code}")


@dataclass(frozen=True)
class Related:
    """One thing on the far end of an edge, and when the edge was made.

    What a read schema needs and no more. It lives here rather than beside the
    queries that build it so a schema can name it without importing a service.

    ``entity`` is None when the thing is gone or the reader cannot open it — the
    edge row cleared the gate but its far end did not, which reads as absent
    rather than as an error.
    """

    id: int
    entity: object | None
    linked_at: datetime


def is_symmetric(relationship_type: RelationshipType) -> bool:
    """Whether this relation is stored once per unordered pair."""
    return SPECS[relationship_type].symmetric


def is_transitive(relationship_type: RelationshipType) -> bool:
    """Whether a walk along this relation may go past one hop."""
    return SPECS[relationship_type].transitive
