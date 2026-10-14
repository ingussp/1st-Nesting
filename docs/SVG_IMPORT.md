# Import multiple SVG files and separate parts

Click **Import SVG** and select one or more files with Ctrl/Shift in the file chooser. Each independent exterior contour becomes a separate part in the workbench table, even when several contours are stored in one SVG `path` or group.

Nested contours stay attached as holes. A material island inside a hole becomes another part. Separate dots, accents and other disconnected material contours are separate parts; they can be arranged together with **Match texture** if they need to retain their relative positions.

The importer preserves native curves, transforms, units and hole boundaries. Preview geometry uses transparent wire outlines. Each table row has the usual quantity, rotation and texture controls. Labels include the source filename and a part number for multi-part files. The FreeCAD object also stores `SVGSourceFile` and `SVGPartNumber`.

All selected files are added in one batch before the preview layout is refreshed. If one file fails, the other files are still imported and one report lists the failed filenames. An invalid/open contour file leaves no partial parts behind. Coincident fill/stroke contour copies are imported once. DXF importing retains its existing behavior.

SVGs should contain closed vector contours. Text should be converted to paths in the source graphics application. Filled SVG boundaries are imported as wires so FreeCAD's automatic fill/cut behavior does not join separate letters or discard hole boundaries differently between versions.

## Verified examples

The two [Deepnest test assets](https://github.com/deepnest-next/deepnest/tree/main/tests/assets) supplied for this change each store many contours inside one SVG path:

| File | Separate material parts | Total contours, including holes |
| --- | ---: | ---: |
| `henny-penny.svg` | 27 | 36 |
| `mrs-saint-delafield.svg` | 27 | 44 |

The counts include disconnected dots/material islands as separate parts. Both files were checked in FreeCAD 1.0 and 1.1; every resulting part passes the same contour preparation used by nesting.

## Verification

Download the two Deepnest SVGs into a local folder, then point `SVG_TEST_ASSETS` at that folder. Run with FreeCAD's bundled Python:

```powershell
$env:SVG_TEST_ASSETS = 'C:\path\to\deepnest-svg-assets'
& "$env:LOCALAPPDATA\Programs\FreeCAD 1.1\bin\python.exe" tests/freecad_svg.py
```

The checks cover real multi-file imports and table rows, both letter fixtures, hole/island nesting, transforms, duplicate contours, overlapping exteriors and cleanup after a failed file. The DXF export integration checks also verify that imported SVG curves remain exportable.
