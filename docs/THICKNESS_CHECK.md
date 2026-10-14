# Part thickness check

1st Nesting checks the thickness of 3D preview parts after additions, removals
and orientation changes, and again before **Run nesting**. Parts with a
different thickness receive a pale red table background, including their
checkbox cells. A warning shows the reference thickness; **Show Details** lists
the differing parts and their measurements.

The most common gauge among distinct source parts is the reference. Equal
counts use the first part's gauge. Quantities and texture-group summary rows do
not add votes. A group containing a differing member is marked along with that
member. Measurements use the current preview orientation along the Z cutting
axis, so correcting a 90-degree orientation can clear the warning. Blind holes
and pockets do not reduce the overall material thickness.

Comparison uses millimetres internally, with a 0.001 mm absolute tolerance for
CAD rounding and a small relative tolerance. Display values follow the selected
mm/inch units. STEP compounds are checked per solid, without mistaking offsets
between solids for thickness. Flat DXF/SVG contours have no defined material
thickness and are excluded from comparison.

The warning is advisory: dismissing it allows nesting to continue. Correcting
the mismatch restores the original table colours. Unchanged mismatches do not
open repeated popups during routine edits; starting a new nesting run checks
and warns again.
