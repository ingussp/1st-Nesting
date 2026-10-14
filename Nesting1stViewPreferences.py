"""Read FreeCAD navigation preferences for every popup wheel event."""
import math
import FreeCAD as App


def wheel_zoom_settings(delta):
    """Return the scene scale and cursor anchoring used by FreeCAD's view.

    FreeCAD increases the camera distance for a positive wheel delta when
    InvertZoom is disabled. A graphics scene scales in the opposite direction.
    Read on each event so an already-open popup follows changed preferences.
    """
    params = App.ParamGet('User parameter:BaseApp/Preferences/View')
    inverted = params.GetBool('InvertZoom', True)
    step = params.GetFloat('ZoomStep', 0.2)
    at_cursor = params.GetBool('ZoomAtCursor', True)
    if not math.isfinite(step) or step < 0:
        step = 0.2
    log_factor = step * float(delta) / 120.0
    if inverted:
        log_factor = -log_factor
    # Match FreeCAD's guard against exceptionally large wheel events.
    factor = math.exp(-log_factor) if abs(log_factor) <= 4.0 else 1.0
    return factor, at_cursor
