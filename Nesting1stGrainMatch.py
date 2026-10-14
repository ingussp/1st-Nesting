"""Texture-matching editor, preview-document persistence and exact group checks."""
import json
import math
import FreeCAD as App
import Part
from PySide import QtCore, QtGui
from Nesting1stLanguages import tr, ui_call, ui_widget, register_window
from Nesting1stGrainMatchModel import polygon, transform, normalize_poses, definition_poses, _convex_hull
from Nesting1stViewPreferences import wheel_zoom_settings


def text(key):
    aliases = {'cancel': 'common.cancel', 'rotate': 'rotate', 'matched': 'perimeter.matched'}
    return tr(aliases.get(key, 'grain_match.'+key))


class ZoomView(QtGui.QGraphicsView):
    """Wheel zoom matching FreeCAD, with middle-button panning."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTransformationAnchor(QtGui.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtGui.QGraphicsView.AnchorViewCenter)
        self._pan_position = None

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self._pan_position = event.pos()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_position is not None:
            delta = event.pos()-self._pan_position
            self._pan_position = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self._pan_position = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        factor, at_cursor = wheel_zoom_settings(delta)
        self.setTransformationAnchor(QtGui.QGraphicsView.AnchorUnderMouse if at_cursor else QtGui.QGraphicsView.AnchorViewCenter)
        self.scale(factor, factor)
        event.accept()


def _profile_face(points):
    return Part.Face(Part.makePolygon([App.Vector(x, y, 0) for x, y in points+points[:1]]))


def _profile_path(points):
    """A consistently wound material polygon for fast Qt collision sweeps."""
    if sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(points, points[1:]+points[:1])) < 0:
        points = list(reversed(points))
    path = QtGui.QPainterPath()
    path.setFillRule(QtCore.Qt.WindingFill)
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    path.closeSubpath()
    return path


def proportional_grid(parts):
    """One tenth of the smallest bbox's shorter side, rounded to whole mm (min 1)."""
    bounds = [(max(p[0] for p in part['points'])-min(p[0] for p in part['points']),
               max(p[1] for p in part['points'])-min(p[1] for p in part['points']))
              for part in parts]
    width, height = min(bounds, key=lambda size: (size[0]*size[1], min(size)))
    step = min(width, height)/10.0
    if not math.isfinite(step) or step <= 0:
        raise ValueError('Every matching part needs a non-zero bounding box.')
    return max(1, int(math.floor(step+.5)))


def display_edges(obj, origin, deflection):
    """Project CAD edges at every depth, including blind machining, like a DXF."""
    from Nesting1stExport import _discretize_edge_2d
    paths, seen = [], set()
    for edge in obj.Shape.Edges:
        points = _discretize_edge_2d(edge, deflection)
        if len(points) < 2:
            continue
        # Top/bottom edges often have identical XY projections. Keep them once.
        key = tuple(tuple(point) for point in points)
        reverse = tuple(reversed(key))
        if key in seen or reverse in seen:
            continue
        seen.add(key)
        paths.append([[x-origin[0], y-origin[1]] for x, y in points])
    return paths


def _boxes_close(a, b, spacing):
    """Cheap broad phase before the precise contour distance/intersection check."""
    dx = max(a.XMin-b.XMax, b.XMin-a.XMax, 0.0)
    dy = max(a.YMin-b.YMax, b.YMin-a.YMax, 0.0)
    return math.hypot(dx, dy) <= spacing+1e-5


def _bounds_close(first, second, spacing):
    return _boxes_close(first.BoundBox, second.BoundBox, spacing)


def _shapes_clear(first, second, spacing, tolerance=1e-5):
    if not _bounds_close(first, second, spacing):
        return True
    distance = first.distToShape(second)[0]
    if distance < spacing-tolerance:
        return False
    # With zero spacing touching is allowed, but common material is not.
    return distance > 1e-5 or first.common(second).Area <= 1e-6


def validate_layout(parts, poses, spacing):
    faces = []
    for part, pose in zip(parts, poses):
        points = transform(part['points'], pose)
        face = _profile_face(points)
        if not face.isValid():
            raise ValueError(text('overlap'))
        # The outer contour is reserved for the group; do not nest group members
        # into one another's holes in this first version.
        for other in faces:
            if not _shapes_clear(face, other, spacing):
                raise ValueError(text('overlap'))
        faces.append(face)



_OBJECT = 'IPNestingGrainMatches'

# Table roles used to mark deactivated members and the summary row.
ROW_KIND_ROLE = QtCore.Qt.UserRole + 2
GROUP_NAMES_ROLE = QtCore.Qt.UserRole + 3
GROUP_ROW_KIND = 'texture_group'
MEMBER_ROW_KIND = 'texture_member'


def row_kind(panel, row):
    """Return the texture-matching marker for a table row, or ''/None."""
    item = panel.table.item(row, 0)
    return item.data(ROW_KIND_ROLE) if item is not None else None


def _set_row_kind(panel, row, kind):
    item = panel.table.item(row, 0)
    if item is not None:
        item.setData(ROW_KIND_ROLE, kind or '')


def read_groups(doc):
    obj = doc.getObject(_OBJECT) if doc else None
    if not obj:
        return []
    groups = json.loads(obj.GroupsJson)
    if not isinstance(groups, list):
        raise ValueError('Invalid texture-matching group data.')
    return groups


def write_groups(doc, groups):
    obj = doc.getObject(_OBJECT)
    if not obj:
        obj = doc.addObject('App::FeaturePython', _OBJECT)
        obj.addProperty('App::PropertyString', 'GroupsJson', 'Texture matching')
        obj.Label = text('title')
    obj.GroupsJson = json.dumps(groups)
    doc.recompute()


class DraggablePart(QtGui.QGraphicsPathItem):
    """Transparent profile with real hole outlines and a solid material hit area."""

    def __init__(self, editor, index, part, pose, colour):
        super().__init__()
        self.editor = editor
        self.index = index
        self.angle = float(pose[2])
        self.colour = QtGui.QColor(colour)
        self._initializing = True
        path = QtGui.QPainterPath()
        path.setFillRule(QtCore.Qt.OddEvenFill)
        for ring in [part['points']] + part.get('holes', []):
            if not ring:
                continue
            path.moveTo(ring[0][0], -ring[0][1])
            for x, y in ring[1:]:
                path.lineTo(x, -y)
            path.closeSubpath()
        self.material_path = path
        if 'display_edges' in part:
            # Display geometry is separate from the material hit area: blind
            # holes must remain selectable, and are not nesting holes.
            path = QtGui.QPainterPath()
            for edge in part['display_edges']:
                path.moveTo(edge[0][0], -edge[0][1])
                for x, y in edge[1:]:
                    path.lineTo(x, -y)
        self.setPath(path)
        self.profile_rect = path.boundingRect()
        self._collision_angle = None
        self.setBrush(QtGui.QBrush(QtCore.Qt.NoBrush))
        self.setFlags(QtGui.QGraphicsItem.ItemIsMovable |
                      QtGui.QGraphicsItem.ItemIsSelectable |
                      QtGui.QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setCursor(QtCore.Qt.OpenHandCursor)
        self.setRotation(-self.angle)
        self.setPos(float(pose[0]), -float(pose[1]))
        self.label = QtGui.QGraphicsSimpleTextItem(part['label'], self)
        self.label.setFlag(QtGui.QGraphicsItem.ItemIgnoresTransformations)
        self.label.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self.label.setBrush(QtGui.QBrush(self.colour))
        self.label.setPos(self.profile_rect.left(), self.profile_rect.bottom())
        self._initializing = False
        self._style()

    def shape(self):
        # Pick parts by their interior as well as the outline, excluding holes.
        return self.material_path

    def collision_profile(self):
        """Cache rotated geometry; dragging only translates it."""
        if self._collision_angle != self.angle:
            self._collision_points = transform(self.editor.parts[self.index]['points'], [0, 0, self.angle])
            self._collision_face = _profile_face(self._collision_points)
            hull = _profile_face(_convex_hull(self._collision_points, precision=None))
            self._collision_convex = abs(hull.Area-self._collision_face.Area) <= 1e-6
            self._collision_angle = self.angle
        return self._collision_points, self._collision_face, self._collision_convex

    def _style(self, hover=False):
        pen = QtGui.QPen(self.colour, 2.5 if self.isSelected() or hover else 1.6)
        pen.setCosmetic(True)
        self.setPen(pen)

    def itemChange(self, change, value):
        if not self._initializing:
            if change == QtGui.QGraphicsItem.ItemPositionChange:
                return self.editor.snap_position(self, value)
            if change == QtGui.QGraphicsItem.ItemPositionHasChanged:
                self.editor.queue_validation()
            elif change == QtGui.QGraphicsItem.ItemSelectedHasChanged:
                self._style()
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        self._style(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._style()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        # One draggable part at a time keeps every collision check authoritative.
        self.scene().clearSelection()
        self.setCursor(QtCore.Qt.ClosedHandCursor)
        self.setZValue(1)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.setCursor(QtCore.Qt.OpenHandCursor)
        self.setZValue(0)
        self.editor.update_layout()


class GrainMatchingDialog(QtGui.QDialog):
    """Arrange every selected part directly in one magnetic workspace."""

    SNAP_PIXELS = 8.0

    def __init__(self, parts, spacing, poses=None, existing=False, parent=None):
        super().__init__(parent)
        self.parts = parts
        self.spacing = float(spacing)
        self.grid_mm = proportional_grid(parts)
        self.removed = False
        self.poses = None
        self.items = []
        self._placing = False
        ui_call(self, 'setWindowTitle', text('title'))
        self.resize(1100, 740)
        self.setMinimumSize(760, 540)
        root = QtGui.QVBoxLayout(self)
        hint = ui_widget(QtGui.QLabel, text('hint'))
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addWidget(ui_widget(QtGui.QLabel, text('workspace_info') % self.spacing))
        self.view = ZoomView()
        self.view.setScene(QtGui.QGraphicsScene(self.view))
        self.view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.view.setBackgroundBrush(QtGui.QBrush(QtGui.QColor('#fafbfc')))
        self.view.setMinimumHeight(300)
        root.addWidget(self.view, 1)
        self.status = QtGui.QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        buttons = QtGui.QHBoxLayout()
        root.addLayout(buttons)
        self.remove_button = ui_widget(QtGui.QPushButton, text('remove'))
        self.remove_button.setEnabled(True)
        self.remove_button.clicked.connect(self.remove_group)
        buttons.addWidget(self.remove_button)
        buttons.addStretch()
        self.rotate_button = ui_widget(QtGui.QPushButton, text('rotate'))
        self.rotate_button.setEnabled(False)
        self.rotate_button.clicked.connect(self.rotate_selected)
        buttons.addWidget(self.rotate_button)
        buttons.addStretch()
        self.view.scene().selectionChanged.connect(self.update_rotate_button)
        self.save_button = ui_widget(QtGui.QPushButton, text('save'))
        self.save_button.clicked.connect(self.accept_group)
        buttons.addWidget(self.save_button)
        cancel = ui_widget(QtGui.QPushButton, text('cancel'))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.validation_timer = QtCore.QTimer(self)
        self.validation_timer.setSingleShot(True)
        self.validation_timer.setInterval(60)
        self.validation_timer.timeout.connect(self.update_layout)
        if poses is None:
            poses = self.initial_poses()
        if len(poses) != len(parts):
            raise ValueError('Every matching part needs a placement.')
        colours = ['#355e83', '#96601d', '#39704a', '#7c4d95', '#a34545', '#277c7d']
        for index, (part, pose) in enumerate(zip(parts, poses)):
            item = DraggablePart(self, index, part, pose, colours[index % len(colours)])
            self.view.scene().addItem(item)
            self.items.append(item)
        self.update_layout()
        register_window(self)
        QtCore.QTimer.singleShot(0, self.fit_workspace)

    def update_rotate_button(self):
        self.rotate_button.setEnabled(len([item for item in self.items if item.isSelected()]) == 1)

    def rotate_selected(self):
        """Rotate the selected part clockwise around its bbox centre, without snapping."""
        selected = [item for item in self.items if item.isSelected()]
        if len(selected) != 1:
            return
        item = selected[0]
        angle = (item.angle-90.0) % 360.0
        centre = item.mapToScene(item.profile_rect.center())
        local = item.profile_rect.center()
        rotated = transform([[local.x(), -local.y()]], [0, 0, angle])[0]
        pose = [centre.x()-rotated[0], -centre.y()-rotated[1], angle]
        poses = self.current_poses()
        poses[item.index] = pose
        self.update_layout()
        try:
            validate_layout(self.parts, poses, self.spacing)
        except ValueError:
            ui_call(self.status, 'setText', text('rotation_blocked'))
            self.status.setStyleSheet('color: #a34545;')
            return
        # Keep the centre and fractional spacing exactly; the invisible grid
        # applies to dragging, not to the geometry of a rotation.
        self.set_part_pose(item.index, pose, snap=False)

    def initial_poses(self):
        """Place all parts in tidy shelves; users can then slide them anywhere."""
        bounds = [(max(x for x, y in part['points']), max(y for x, y in part['points']))
                  for part in self.parts]
        side = max(max(width for width, height in bounds),
                   math.sqrt(sum(width*height for width, height in bounds))*1.4)
        grid = self.grid_mm
        gap = math.ceil(max(20.0, self.spacing)/grid)*grid
        x = y = row_height = 0.0
        poses = []
        for width, height in bounds:
            if x and x+width > side:
                x = 0.0
                y += math.ceil((row_height+gap)/grid)*grid
                row_height = 0.0
            poses.append([x, y, 0.0])
            x += math.ceil((width+gap)/grid)*grid
            row_height = max(row_height, height)
        return poses

    def snap_position(self, item, position):
        if self._placing:
            return position
        grid = self.grid_mm
        coordinates = [round(position.x()/grid)*grid, round(position.y()/grid)*grid]
        current = item.mapRectToScene(item.profile_rect)
        offsets = [[current.left()-item.pos().x(), current.center().x()-item.pos().x(), current.right()-item.pos().x()],
                   [current.top()-item.pos().y(), current.center().y()-item.pos().y(), current.bottom()-item.pos().y()]]
        tolerance = self.SNAP_PIXELS/max(abs(self.view.transform().m11()), 1e-6)
        for axis, desired in enumerate((position.x(), position.y())):
            candidates = []
            for other in self.items:
                if other is item:
                    continue
                bounds = other.mapRectToScene(other.profile_rect)
                anchors = [bounds.left(), bounds.center().x(), bounds.right()] if axis == 0 else [bounds.top(), bounds.center().y(), bounds.bottom()]
                candidates.extend(anchor-offset for anchor in anchors for offset in offsets[axis])
                # Magnetic gaps also make it easy to respect the nesting spacing.
                candidates.extend([anchors[-1]+self.spacing-offsets[axis][0],
                                   anchors[0]-self.spacing-offsets[axis][-1]])
            if candidates:
                closest = min(candidates, key=lambda value: abs(value-desired))
                if abs(closest-desired) <= tolerance:
                    coordinates[axis] = closest
        return self.constrain_position(item, QtCore.QPointF(*coordinates))

    def constrain_position(self, item, target):
        """Stop at the first collision along the drag, then slide along its edge."""
        points, local_face, convex = item.collision_profile()
        start = item.pos()
        others = []
        barriers = []
        stroker = QtGui.QPainterPathStroker()
        stroker.setJoinStyle(QtCore.Qt.RoundJoin)
        stroker.setCapStyle(QtCore.Qt.RoundCap)
        stroker.setWidth(2*self.spacing)
        stroker.setCurveThreshold(.0001)
        for other in self.items:
            if other is item:
                continue
            face = other.collision_profile()[1].copy()
            face.translate(App.Vector(other.pos().x(), -other.pos().y(), 0))
            others.append(face)
            other_points = [[x+other.pos().x(), y-other.pos().y()] for x, y in other.collision_profile()[0]]
            path = _profile_path(other_points)
            # Circular joins represent the Euclidean minimum-distance zone.
            # The exact FreeCAD distance below also guards stroke approximation.
            if self.spacing > 0:
                path = path.united(stroker.createStroke(path))
            barriers.append(path)

        def face_at(position):
            face = local_face.copy()
            face.translate(App.Vector(position.x(), -position.y(), 0))
            return face

        def clear(shape, obstacles=None):
            # Stop slightly inside the validator's tolerance so rounding the
            # saved coordinates cannot invalidate a boundary placement.
            return all(_shapes_clear(shape, other, self.spacing, tolerance=1e-6)
                       for other in (others if obstacles is None else obstacles))

        def sweep(first, last):
            dx, dy = last.x()-first.x(), first.y()-last.y()
            if math.hypot(dx, dy) < 1e-9:
                return _profile_path([[x+first.x(), y-first.y()] for x, y in points])
            initial = [[x+first.x(), y-first.y()] for x, y in points]
            final = [[x+dx, y+dy] for x, y in initial]
            if convex:
                return _profile_path(_convex_hull(initial+final, precision=None))
            # The union of both endpoint profiles and swept boundary strips is
            # the exact region traversed by a translating concave polygon.
            region = _profile_path(initial)
            region.addPath(_profile_path(final))
            for a, b in zip(initial, initial[1:]+initial[:1]):
                if abs((b[0]-a[0])*dy-(b[1]-a[1])*dx) > 1e-9:
                    region.addPath(_profile_path([a, b, [b[0]+dx, b[1]+dy], [a[0]+dx, a[1]+dy]]))
            return region

        def advance(first, last):
            a, b = face_at(first).BoundBox, face_at(last).BoundBox
            bounds = App.BoundBox(min(a.XMin,b.XMin), min(a.YMin,b.YMin), 0,
                                 max(a.XMax,b.XMax), max(a.YMax,b.YMax), 0)
            indices = [i for i, other in enumerate(others) if _boxes_close(bounds, other.BoundBox, self.spacing)]
            obstacles = [others[i] for i in indices]
            # Avoid constructing many swept strips when a curved profile is
            # being dragged in open space, far from any other part.
            def allowed(position):
                region = sweep(first, position)
                return (all(region.intersected(barriers[i]).isEmpty() for i in indices) and
                        clear(face_at(position), obstacles))
            if not obstacles or allowed(last):
                return last
            low, high = 0.0, 1.0
            delta = last-first
            for _ in range(26):
                middle = (low+high)/2
                if allowed(first+delta*middle):
                    low = middle
                else:
                    high = middle
            return first+delta*low

        if not clear(face_at(start)):
            # A saved group may become invalid when spacing is increased.
            # Let the user pull it apart, while Save remains guarded.
            def violation(position):
                face = face_at(position)
                return sum(max(0.0, self.spacing-face.distToShape(other)[0]) +
                           math.sqrt(max(0.0, face.common(other).Area))
                           for other in others if _bounds_close(face, other, self.spacing))
            return target if violation(target) < violation(start)-1e-7 else start

        result = advance(start, target)
        if (result-target).manhattanLength() > 1e-5:
            horizontal = advance(result, QtCore.QPointF(target.x(), result.y()))
            vertical = advance(result, QtCore.QPointF(result.x(), target.y()))
            result = min((result, horizontal, vertical),
                         key=lambda pos: (pos.x()-target.x())**2+(pos.y()-target.y())**2)
        return result

    def current_poses(self):
        return [[item.pos().x(), -item.pos().y(), item.angle] for item in self.items]

    def set_part_pose(self, index, pose, snap=True):
        """Move an item through the same snapping path used by mouse dragging."""
        item = self.items[index]
        self._placing = not snap
        try:
            item.angle = float(pose[2])
            item.setRotation(-item.angle)
            item.setPos(float(pose[0]), -float(pose[1]))
        finally:
            self._placing = False
        self.update_layout()

    def queue_validation(self):
        self.poses = None
        self.save_button.setEnabled(False)
        self.validation_timer.start()

    def update_layout(self):
        self.validation_timer.stop()
        self.poses = None
        try:
            if len({part.get('quantity', 1) for part in self.parts}) > 1:
                raise ValueError(text('equal'))
            poses = normalize_poses(self.parts, self.current_poses())
            validate_layout(self.parts, poses, self.spacing)
            self.poses = poses
            ui_call(self.status, 'setText', text('ready'))
            self.status.setStyleSheet('color: #39704a;')
        except ValueError as exc:
            ui_call(self.status, 'setText', exc.args[0] if exc.args else str(exc))
            self.status.setStyleSheet('color: #a34545;')
        self.save_button.setEnabled(self.poses is not None)

    def fit_workspace(self):
        if not self.items:
            return
        rect = self.items[0].mapRectToScene(self.items[0].profile_rect)
        for item in self.items[1:]:
            rect = rect.united(item.mapRectToScene(item.profile_rect))
        margin = max(rect.width(), rect.height())*.12+20
        scene_rect = rect.adjusted(-margin, -margin, margin, margin)
        self.view.scene().setSceneRect(scene_rect)
        self.view.fitInView(scene_rect, QtCore.Qt.KeepAspectRatio)
        # Leave space to arrange parts outside the initial layout without auto-fitting.
        travel = max(rect.width(), rect.height(), 200)*4
        self.view.scene().setSceneRect(scene_rect.adjusted(-travel, -travel, travel, travel))
        self.view.centerOn(rect.center())

    def remove_group(self):
        self.removed = True
        self.accept()

    def accept_group(self):
        self.update_layout()
        if self.poses is not None:
            self.accept()


def open_editor(panel):
    from Nesting1stExport import _extract_part_points, _read_boundary_deflection, _extract_part_candidate_wires
    rows = sorted({index.row() for index in panel.table.selectionModel().selectedRows()
                   if index.row() < panel.table.rowCount()-panel.control_rows})
    doc = App.getDocument(panel.preview_doc_name)
    selected = {panel._primary_name_for_row(row) for row in rows}
    groups = read_groups(doc)
    matching = [group for group in groups if selected.intersection(group['names'])]
    if len(matching) > 1:
        raise ValueError(text('single_group'))
    existing = matching[0] if matching else None
    if existing:
        selected.update(existing['names'])
    entries = {}
    for row in range(panel.table.rowCount()-panel.control_rows):
        if row_kind(panel, row) == GROUP_ROW_KIND:
            continue
        name = panel._primary_name_for_row(row)
        if name not in selected:
            continue
        obj = doc.getObject(name)
        if obj is None:
            continue
        deflection = _read_boundary_deflection(panel)
        candidates = _extract_part_candidate_wires(obj, deflection)
        points = _extract_part_points(obj, candidates=candidates)
        origin = [min(p[k] for p in candidates[0]) for k in (0, 1)]
        # Show all physical through holes, independently of the nesting hole selection.
        holes = [[[x-origin[0], y-origin[1]] for x, y in hole] for hole in candidates[1:]]
        entries[name] = dict(name=name, label=panel.table.item(row, 0).text(),
            quantity=int(panel.table.item(row, 1).text()), points=points, holes=holes, origin=origin,
            display_edges=display_edges(obj, origin, deflection))
    names = [name for name in existing['names'] if name in entries] if existing else list(entries)
    names += [name for name in entries if name not in names]
    parts = [entries[name] for name in names]
    if len(parts) < 2 and not existing:
        raise ValueError(text('select'))
    if len({part['quantity'] for part in parts}) > 1 and not existing:
        raise ValueError(text('equal'))
    spacing = panel.get_dimension_value_mm(panel.spacing, 6.0)
    poses = None
    if existing and names == existing['names']:
        if existing.get('preview_assembled'):
            minimum = [min(part['origin'][k] for part in parts) for k in (0, 1)]
            poses = [[part['origin'][0]-minimum[0], part['origin'][1]-minimum[1], 0.0] for part in parts]
        else:
            poses = definition_poses(parts, existing, spacing)
    dialog = GrainMatchingDialog(parts, spacing, poses, bool(existing), panel.form)
    if dialog.exec_() != QtGui.QDialog.Accepted:
        return
    replacement = [group for group in groups if group is not existing]
    if existing:
        # The editor starts from displayed geometry. Do not restore older placements
        # or rotations over the arrangement the user has just approved.
        for name in existing['names']:
            obj = doc.getObject(name)
            if obj is not None:
                for property_name in ('IPNestingStandardPlacement', 'IPNestingStandardRotations', 'IPNestingCustomAngleDeg'):
                    if hasattr(obj, property_name):
                        obj.removeProperty(property_name)
        from Nesting1stGrain import GrainPreparer
        GrainPreparer.update_group_grain_arrow(doc.Name, existing['names'], enable=False)
    if not dialog.removed:
        new_group = dict(names=names, outlines=[polygon(part['points']) for part in parts],
                         manual_poses=dialog.poses)
        if existing:
            new_group['rotations'] = existing.get('standard_rotations',
                                                  existing.get('rotations', str(panel.get_default_rotations())))
        replacement.append(new_group)
    write_groups(doc, replacement)
    refresh_labels(panel, replacement)
    if dialog.removed:
        panel.table.clearSelection()
    _refresh_grain_layout(panel)


def _refresh_grain_layout(panel):
    """Re-run the live grain layout so freshly grouped parts move to their square."""
    try:
        controller = getattr(panel, '_grain', None)
        if controller is not None:
            controller._apply_live_layout()
    except Exception:
        pass


def _matched_part_info(panel, groups):
    """Map each group to the (labels, quantity, names) currently shown in the table."""
    info = {}
    for row in range(panel.table.rowCount()-panel.control_rows):
        item = panel.table.item(row, 0)
        if item is None or row_kind(panel, row) == GROUP_ROW_KIND:
            continue
        name = panel._primary_name_for_row(row)
        if not name:
            continue
        quantity = 1
        qty_item = panel.table.item(row, 1)
        if qty_item is not None:
            try:
                quantity = int(str(qty_item.text()).strip())
            except Exception:
                quantity = 1
        info[name] = (item.text(), quantity)
    result = []
    for group in groups:
        names = [n for n in group.get('names', []) if n in info]
        if not names:
            continue
        result.append(([info[n][0] for n in names], info[names[0]][1], names))
    return result


def _set_member_row_active(panel, row, active):
    """Grey out (or restore) a part row and disable (or enable) its controls."""
    try:
        for col in range(panel.table.columnCount()):
            item = panel.table.item(row, col)
            if item is None:
                continue
            flags = item.flags()
            if active:
                flags |= QtCore.Qt.ItemIsEditable
                item.setBackground(QtGui.QBrush())
            else:
                flags &= ~QtCore.Qt.ItemIsEditable
                item.setBackground(QtGui.QBrush(QtGui.QColor('#e4e4e4')))
            item.setFlags(flags)
        for col in (3, 4, 5):
            widget = panel.table.cellWidget(row, col)
            if widget is None:
                continue
            for checkbox in widget.findChildren(QtGui.QCheckBox):
                checkbox.setEnabled(active)
            for combo in widget.findChildren(QtGui.QComboBox):
                combo.setEnabled(active)
    except Exception:
        pass


def _render_summary_rows(panel, groups):
    """Replace texture-matched summary rows with one full part row per group."""
    table = panel.table
    states = {}
    for row in range(table.rowCount()-panel.control_rows-1, -1, -1):
        if row_kind(panel, row) == GROUP_ROW_KIND:
            key = tuple(json.loads(table.item(row, 0).data(GROUP_NAMES_ROLE)))
            states[key] = [bool(table.cellWidget(row, col).findChild(QtGui.QCheckBox).isChecked())
                           for col in (3, 5)]
            table.removeRow(row)
    pos = max(0, table.rowCount()-panel.control_rows)
    for labels, quantity, names in _matched_part_info(panel, groups):
        table.insertRow(pos)
        definition = next(g for g in groups if set(g['names']) == set(names))
        _fill_group_row(panel, pos, labels, quantity, names, definition)
        for col, checked in zip((3, 5), states.get(tuple(names), (False, False))):
            table.cellWidget(pos, col).findChild(QtGui.QCheckBox).setChecked(checked)
        pos += 1
    for row in range(table.rowCount()-panel.control_rows):
        table.setVerticalHeaderItem(row, QtGui.QTableWidgetItem(str(row+1)))


def _fill_group_row(panel, row, labels, quantity, names, definition=None):
    """Populate a group row like a new part, named `Texture matched parts: …`."""
    table = panel.table
    definition = definition or {}
    name_item = ui_widget(QtGui.QTableWidgetItem,
                         tr('s_s_d9cd37') % (text('matched'), ', '.join(labels)))
    name_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
    name_item.setBackground(QtGui.QBrush(QtGui.QColor('#e5f1df')))
    name_item.setData(ROW_KIND_ROLE, GROUP_ROW_KIND)
    name_item.setData(GROUP_NAMES_ROLE, json.dumps(names))
    name_item.setData(QtCore.Qt.UserRole, names[0])
    name_item.setData(QtCore.Qt.UserRole + 1, json.dumps(names))
    table.setItem(row, 0, name_item)

    qty_item = QtGui.QTableWidgetItem(str(quantity))
    qty_item.setTextAlignment(QtCore.Qt.AlignCenter)
    table.setItem(row, 1, qty_item)

    rotations_item = QtGui.QTableWidgetItem('[0, 180]' if definition.get('grain')
                                          else str(definition.get('rotations', panel.get_default_rotations())))
    rotations_item.setTextAlignment(QtCore.Qt.AlignCenter)
    table.setItem(row, 2, rotations_item)

    table.setCellWidget(row, 3, _centered_checkbox())
    grain_widget = _grain_widget()
    grain_widget.findChild(QtGui.QCheckBox).setChecked(bool(definition.get('grain')))
    grain_widget.findChild(QtGui.QComboBox).setCurrentIndex(1 if definition.get('grain') == 'Y' else 0)
    table.setCellWidget(row, 4, grain_widget)
    _connect_group_grain_widgets(panel, names, grain_widget)
    table.setCellWidget(row, 5, _centered_checkbox())

    vertical = QtGui.QTableWidgetItem(str(row+1))
    table.setVerticalHeaderItem(row, vertical)


def rotate_preview_group(doc, names, angle, axis=None):
    """Rotate every member about one shared centre, preserving the assembly."""
    objects = [doc.getObject(name) for name in names]
    objects = [obj for obj in objects if obj is not None]
    if not objects:
        return
    bounds = App.BoundBox()
    for obj in objects:
        bounds.add(obj.Shape.BoundBox)
    centre = bounds.Center
    rotation = App.Rotation(axis or App.Vector(0, 0, 1), float(angle))
    change = App.Placement(centre - rotation.multVec(centre), rotation)
    for obj in objects:
        obj.Placement = change.multiply(obj.Placement)
    doc.recompute()


def prepare_preview_groups(panel, doc):
    """Apply the saved manual arrangement once before packing as a rigid unit."""
    from Nesting1stExport import _extract_part_candidate_wires, _read_boundary_deflection
    groups = read_groups(doc)
    changed = False
    spacing = panel.get_dimension_value_mm(panel.spacing, 6.0)
    for group in groups:
        if group.get('preview_assembled'):
            continue
        members = [dict(points=outline) for outline in group['outlines']]
        for member, boundary in zip(members, group.get('matching_edges', [])):
            member['matching_edges'] = boundary
        poses = definition_poses(members, group, spacing)
        validate_layout(members, poses, spacing)
        objects = [doc.getObject(name) for name in group['names']]
        if any(obj is None for obj in objects):
            raise ValueError('A texture-matching part was removed. Edit or remove its matching group.')
        group['source_rotations'] = [list(obj.Placement.Rotation.Q) for obj in objects]
        for obj, member, pose in zip(objects, members, poses):
            turn = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), pose[2]))
            obj.Placement = turn.multiply(obj.Placement)
            candidates = _extract_part_candidate_wires(obj, _read_boundary_deflection(panel))
            wanted = transform(member['points'], pose)
            delta = App.Vector(min(p[0] for p in wanted)-min(p[0] for p in candidates[0]),
                               min(p[1] for p in wanted)-min(p[1] for p in candidates[0]), 0)
            obj.Placement.Base = obj.Placement.Base + delta
        group['preview_assembled'] = True
        changed = True
    if changed:
        write_groups(doc, groups)


def _connect_group_grain_widgets(panel, names, grain_widget):
    """Wire a group row's grain checkbox/combo to the panel's grain controller."""
    try:
        controller = getattr(panel, '_grain', None)
        if controller is None:
            return
        cb = grain_widget.findChild(QtGui.QCheckBox)
        combo = grain_widget.findChild(QtGui.QComboBox)
        if cb is not None and combo is not None:
            controller._connect_group_grain_widgets(names, cb, combo)
    except Exception:
        pass


def _centered_checkbox():
    """Build the standard centred checkbox container used by part rows."""
    widget = QtGui.QWidget()
    layout = QtGui.QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addStretch()
    layout.addWidget(QtGui.QCheckBox())
    layout.addStretch()
    return widget


def _grain_widget():
    """Build the grain-direction checkbox + axis combo used by part rows."""
    widget = QtGui.QWidget()
    layout = QtGui.QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.addStretch()
    layout.addWidget(QtGui.QCheckBox())
    combo = QtGui.QComboBox()
    combo.addItems(['X', 'Y'])
    combo.setCurrentIndex(0)
    combo.setFixedWidth(70)
    layout.addWidget(combo)
    layout.addStretch()
    return widget


def refresh_labels(panel, groups=None):
    blocked = panel.table.blockSignals(True)
    try:
        _refresh_labels(panel, groups)
    finally:
        panel.table.blockSignals(blocked)


def _refresh_labels(panel, groups=None):
    """Deactivate matched member rows and keep a bottom summary row up to date."""
    if groups is None:
        groups = read_groups(App.getDocument(panel.preview_doc_name))
    matched = set()
    for group in groups:
        matched.update(group.get('names', []))
    for row in range(panel.table.rowCount()-panel.control_rows):
        if row_kind(panel, row) == GROUP_ROW_KIND:
            continue
        name = panel._primary_name_for_row(row)
        is_member = bool(name and name in matched)
        _set_row_kind(panel, row, MEMBER_ROW_KIND if is_member else None)
        _set_member_row_active(panel, row, not is_member)
        item = panel.table.item(row, 0)
        if item is not None:
            group = next((i for i, g in enumerate(groups, 1) if name in g['names']), None)
            item.setToolTip(('%s %d' % (text('title'), group)) if group else '')
    _render_summary_rows(panel, groups)
