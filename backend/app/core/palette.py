"""The colours Initiative picks a new row's colour from.

Muted mid-tones spanning the wheel, so a grid of randomly coloured rows reads
as calm and each stays distinct. A built-in counter takes one as it is made,
and a tool plug-in's colour field that defaults to ``random`` takes one per
row from its column's default. The frontend reads them from ``tools.json``
(``scripts/build_tool_records.py``).
"""

from __future__ import annotations

COLOR_PALETTE: tuple[str, ...] = (
    # reds / roses
    "#C25B5B",
    "#B5746B",
    "#C77B7B",
    # oranges
    "#C2855B",
    "#BC8A5F",
    "#CC8E63",
    # ambers / yellows
    "#C2A35B",
    "#B8A55C",
    "#C7B86A",
    # limes / greens
    "#9DB063",
    "#84A35C",
    "#6FA06B",
    "#5FA07E",
    # teals / cyans
    "#5B9E9E",
    "#5F97A0",
    "#6B8F9E",
    # blues
    "#5B7FC2",
    "#6B82B5",
    "#7088B0",
    # indigos / violets
    "#6F6FB0",
    "#7B6BB5",
    "#8A6FB0",
    # purples / orchids
    "#9E6BA0",
    "#A86B97",
    "#B06B8A",
    # pinks
    "#C25B86",
    "#B57088",
    # warm / cool neutrals
    "#8A7B6B",
    "#9E8F7E",
    "#7E8579",
)
