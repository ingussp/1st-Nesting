# Single-piece offcut

The result information shows **Single-piece offcut** directly below **Sheet waste**.
It is the largest connected reusable piece on a sheet containing placed parts,
not the sum of all waste and not the bounding box of the nested layout. With
multiple sheets, the percentage refers to the sheet containing that piece.
Untouched sheets are not counted as offcuts.

The green outline in `Nesting_Result` shows the measured boundary, including any
holes. It follows the material left around the placed parts. The CLI reserves
the configured part, sheet and hole clearances, then removes narrow connections
using a minimum width of **Part spacing + 1 mm**. The calculation uses inward
and outward polygon offsets and selects one connected recovered component.
Narrow slots and necks cannot join otherwise separate reusable pieces.

All geometry and area values stay in millimetres and square millimetres. The
display converts the new area to square inches when the panel uses inches;
the extra 1 mm in the width rule always remains 1 mm. Results include this
measurement in both First (fast) and Continuous modes with the accompanying
CLI build. Older or disabled measurements are shown as unavailable, not zero.

Texture-matched groups retain the engine's conservative reserved-envelope
measurement after expanding their members. The outline is therefore safe to
reuse, but the reserved space inside a texture group is not added to its area.

The SVG report includes the same area and contour. DXF part export excludes
the green annotation, so it does not become an extra cutting contour.
