"""Shared, canonical CLI search settings for the Settings menu and export."""
import math

PREFERENCES = "User parameter:BaseApp/Preferences/Mod/IPNesting"
# Keep the existing preference keys, including their string storage format.
SEARCH_SETTINGS = {
    "resolution": ("Resolution", 1.0, 1e-6, 1000000.0, False),
    "bitmapSearchStepPx": ("SearchStepPx", 1, 1, 100000, True),
    "curveTolerance": ("CurveTolerance", 0.3, 0.0, 1000000.0, False),
}


def _preferences():
    try:
        import FreeCAD as App
        return App.ParamGet(PREFERENCES)
    except Exception:
        return None


def _number(value, default, minimum, maximum, integer):
    try:
        result = float(str(value).replace(',', '.'))
        if not math.isfinite(result):
            raise ValueError('Non-finite setting')
    except (ValueError, TypeError, OverflowError):
        result = default
    result = max(minimum, min(maximum, result))
    return int(round(result)) if integer else result


def read_search_settings(preferences=None):
    """Read validated values without depending on open panel/menu widgets."""
    preferences = preferences if preferences is not None else _preferences()
    result = {}
    for name, (key, default, minimum, maximum, integer) in SEARCH_SETTINGS.items():
        try:
            value = preferences.GetString(key, str(default))
        except Exception:
            value = default
        result[name] = _number(value, default, minimum, maximum, integer)
    try:
        result['cacheRejects'] = bool(preferences.GetBool('CacheRejects', True))
    except Exception:
        result['cacheRejects'] = True
    return result


def write_search_setting(name, value, preferences=None):
    """Persist a validated setting under its existing FreeCAD preference key."""
    preferences = preferences if preferences is not None else _preferences()
    if preferences is None:
        return
    if name == 'cacheRejects':
        preferences.SetBool('CacheRejects', bool(value))
    else:
        key, default, minimum, maximum, integer = SEARCH_SETTINGS[name]
        number = _number(value, default, minimum, maximum, integer)
        preferences.SetString(key, str(number) if integer else format(number, '.12g'))


def read_gpu_batch_size(preferences=None):
    """Read the existing GPU batch preference independently of panel widgets."""
    preferences = preferences if preferences is not None else _preferences()
    try:
        value = preferences.GetString('GpuBatchSize', '65536')
    except Exception:
        value = 65536
    return _number(value, 65536, 256, 262144, True)


def write_gpu_batch_size(value, preferences=None):
    """Keep the same preference key and string format used by the main panel."""
    preferences = preferences if preferences is not None else _preferences()
    if preferences is not None:
        preferences.SetString('GpuBatchSize', str(_number(value, 65536, 256, 262144, True)))
