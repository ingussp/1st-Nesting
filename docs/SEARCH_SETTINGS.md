# Search settings

The main panel offers two translated search modes. `input.json` and the saved
`SearchMode` preference use fixed CLI identifiers:

| Mode in English | JSON identifier | Total time limit | Initial-layout budget |
| --- | --- | --- | --- |
| Fast | `first` | Disabled; exported as 0 | Disabled |
| Continuous | `continuous` | Enabled; 0 = unlimited | Enabled |

`config.timeLimitSeconds` is the Continuous total budget, from 0 to 86,400 seconds.
It includes preparation, the initial layout and CPU/GPU workers. Fractional seconds
are accepted. First always exports zero, retaining the saved deadline in the UI
for switching back to Continuous.

`config.continuousRoundSeconds` bounds the initial-layout search, from 0.01 to
86,400 seconds, capped by the remaining total time. Cancellation and deadlines
are cooperative: active geometry/GPU calls and output can add time.

Previously saved `timed` preferences migrate to `continuous` without changing
`TimeLimitSeconds`. New jobs never export the retired mode. The engine chooses
its own search strategies; the old placement-strategy control and its `trials`
field are removed. `algorithm` is also absent from the current CLI schema.

The process is started with `clinesting --input input.json`. Modes and budgets
are JSON settings, not additional command-line flags. FreeCAD metadata is stored
in `nesting_session.json`, while input polygons may use the accepted `name` field.

## Advanced settings

The gear/Settings menu contains the advanced search settings directly below the
contour approximation tolerance:

1. Bitmap resolution (mm/px).
2. Search step (px).
3. Cache rejected positions.
4. Contact simplification (mm).
5. Batch size (GPU), directly below Contact simplification.

These retain the existing preference keys (`Resolution`, `SearchStepPx`,
`CacheRejects`, `CurveTolerance`, `GpuBatchSize`), so existing values survive moving the controls.
The exporter reads them at the start of each job, including edits made while the
main panel is open. The menu is also available when no task panel is open.

Batch size defaults to 65,536 and accepts values from 256 to 262,144. It controls
GPU batching and retains the `GpuBatchSize` preference.

Below Batch size, the CLI-nesting row contains **Check for updates**. It explicitly
checks for the latest stable engine release and offers a matching system download;
opening Settings does not start a network request. See [engine updates](ENGINE_UPDATES.md).

## The two geometric tolerances

Contour approximation tolerance (`BoundaryResolution`, default 0.01 mm) belongs
to FreeCAD. It controls the maximum deviation when curved edges are discretized
into line segments, and affects the polygons exported to `input.json`.

Contact simplification (`curveTolerance` in the CLI JSON, default 0.3 mm) belongs
to the CLI. In the current bitmap engine it simplifies the contour used to
propose contact positions. The raster occupancy, vector validation and exported
result geometry retain the original contour. A value of zero disables this
simplification. It is a separate operation, so it remains available in Settings
under a clearer name instead of being removed as a duplicate.

Bitmap resolution is a third parameter: the size of one raster pixel. All three
use canonical millimetres even if the main panel displays sheet dimensions in
inches.
