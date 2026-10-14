# Manual laser-cutting bridges (prototype)

Create bridges after nesting to join selected outer contours into larger cutting profiles. The original nesting placement stays fixed.

1. Run nesting, then click **Create bridges** next to **Match texture**.
2. Select a sheet when the result contains more than one sheet.
3. Enter **Bridge width**. The input and bridge list follow the main window's mm/inch selection. All calculations, saved points and bridge widths remain in millimetres; 1 inch is 25.4 mm.
4. Click an outer edge of the first part, then an outer edge of another part. Clicks snap to the nearest outer edge within a small screen-space tolerance. Holes and internal machining lines are displayed, but are not attachment targets.
5. Use the mouse wheel to zoom, hold and drag the left mouse button to pan, and **Fit all** to fit the sheet. A short left click selects an edge; dragging does not add bridge endpoints. Middle-button panning also works. Right-click or **Cancel first point** to clear a pending endpoint.
6. Inspect the bridge list below the preview. Select one or more rows and click **Delete selected**, or press Delete while the list has focus.
7. Click **OK** to create a new **Nesting_Bridges** FreeCAD document. Cancel leaves the original result unchanged.

Each part has its own colour. Orange polygons mark bridges; selected list rows highlight their bridges. The preview includes the sheet and actual outer/inner contours, not bounding boxes.

Mouse-wheel zoom follows FreeCAD's **Invert zoom**, **Zoom step** and **Zoom at cursor** preferences, shared with texture matching and part/sheet previews. Changes to these preferences also apply to already-open popup windows.

The entire bridge width is checked against other parts and the usable sheet, including sheet holes. Both attachment points must lie on different parts on the same sheet. Only a local overlap at each attachment is allowed; a bridge cannot traverse the interior of either endpoint part or cover its selected nesting holes. A rejected bridge is not added to the list.

## Generated geometry

Each connected bridge network becomes a single **Joined parts** object (`JoinedParts_...`). Unconnected parts remain separate objects. There are no separate bridge objects or duplicate cutting-contour overlays in the output.

For a group of 3D solids, the original CAD shapes and bridge solids are Boolean-fused and refined into one solid. Through holes, blind pockets and original CAD surfaces are preserved. A bridge spans the common height of its two endpoint solids; a group that cannot form one valid solid is rejected before a new document is created.

For DXF/SVG/2D profiles, the material faces and bridge strips become one planar face with a single exterior wire and preserved inner hole wires. Internal shared edges are removed. A mixed group containing both planar profiles and 3D solids produces a planar cutting profile; its original source shapes remain available for editing.

Select **Joined parts** objects when exporting to CAM (for example, STEP for 3D solids or DXF for planar profiles). The separate **Sheet** object is the stock outline. Original source geometry is stored as BREP text in non-geometric metadata, so it does not add overlapping part boundaries to a CAM export.

The prototype creates geometry, not machine-specific G-code, pierce settings, kerf compensation or an optimized cutting sequence. CAM software remains responsible for machining these profiles. 3D Boolean unions retain the original CAD surfaces and machining features. Planar cutting profiles use the engine's sampled contours.

Saving the generated FCStd document saves the bridge list in millimetres and the original per-part CAD snapshots. Reopen it, make it the active document, and click **Create bridges** to edit a copy, including deleting bridges and splitting a network back into separate parts. The first prototype's older overlapping-bridge documents can also be opened in the editor and converted by saving a new result. Newly generated Nesting_Result documents retain the contour snapshot needed by the editor after saving/reopening.

## Verification

Run with FreeCAD's bundled Python:

```powershell
& "$env:LOCALAPPDATA\Programs\FreeCAD 1.1\bin\python.exe" tests/freecad_bridges.py
```

The integration checks exercise real CAD unions, full-width collisions, endpoint/hole/sheet checks, 2D and 3D output, mm/inch conversion, mouse clicks, deletion, saved-document reopening and the main panel/result importer integration.
