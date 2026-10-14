# Export a nesting result to DXF

The bottom row contains two equally sized export buttons: **Export nesting result to SVG** and **Export to DXF**.

1. Add FreeCAD parts, STEP models, DXF profiles or SVG profiles and run nesting.
2. Keep **Nesting_Result** active. To export connected parts instead, create bridges and keep **Nesting_Bridges** active. Saved result documents can also be reopened and exported.
3. Click **Export to DXF**, choose a filename and save it.
4. Open the DXF in your CAD/CAM application. Coordinates and the file's unit declaration are **millimetres**, including when the workbench displays inches.

The exporter uses the actual placed FreeCAD BREP geometry. A STEP file becomes CAD geometry on import; no new STEP conversion is required for DXF export. FreeCAD objects, STEP models, DXF and SVG profiles use the same export path. Engine-sampled polygons and bounding boxes are not used to recreate contours.

Solid parts are projected from above, in the displayed nesting orientation. Visible outlines, through holes and visible machining details, such as blind pockets, are included. Planar profiles are flattened to XY. Lines, circular arcs, circles and ellipses stay analytic DXF entities. B-splines keep their control points, knots and rational weights, including circular profiles that older SVG importers represent as NURBS. Bezier curves are converted exactly to B-splines.

Each placed part or joined bridge network has its own layer named `Sheet_<number>_<object name>`. Multiple sheets retain their displayed offsets. Stock borders, result labels and unplaced parts are excluded. Duplicate projected edges are removed. The document and its source geometry are not modified; an export failure preserves an existing output file.

This is a 2D top-view CAD export. Hidden machining on the back of a solid is not included. Visible pockets remain drawing geometry, so select the intended contours and machining operations in CAM.

The first prototype's older bridge documents must be reopened in **Create bridges** and saved with **OK** to obtain joined geometry before exporting.

## Verification

Run with FreeCAD's bundled Python:

```powershell
& "$env:LOCALAPPDATA\Programs\FreeCAD 1.1\bin\python.exe" tests/freecad_dxf.py
```

The tests use real FreeCAD shapes and real STEP, DXF and SVG input files. Exported DXFs are read back with FreeCAD's native importer to check dimensions, positions, perimeter lengths and curve preservation. Additional checks cover bridge perimeters, NURBS weights, Bezier curves, visible pockets, saved results, failure cleanup and the two-button layout.
