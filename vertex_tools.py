bl_info = {
    "name": "Vertex Tools",
    "author": "Baris",
    "version": (2, 0, 0),
    "blender": (3, 0, 0),
    "location": "3D Viewport > Edit Mode > N Panel > Tool > Vertex Tools, and Vertex / Mesh menus",
    "description": "Average Vertex: fix or extend a chain of vertices (line, curve or average). "
                   "Draw With Vertex: click points on a plane to build a face",
    "category": "Mesh",
}

import math

import bpy
import bmesh
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from mathutils import Vector, geometry


# ############################################################################
#
#   AVERAGE VERTEX
#
# ############################################################################

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def fit_line(pts):
    """Least-squares line through points. Returns (centroid, unit direction) or None."""
    arr = np.array([tuple(p) for p in pts], dtype=float)
    centroid = arr.mean(axis=0)
    _, s, vt = np.linalg.svd(arr - centroid, full_matrices=False)
    if s[0] < 1e-9:
        return None
    return Vector(centroid.tolist()), Vector(vt[0].tolist()).normalized()


def _closest_u(coefs, target, u0, u1):
    """Curve parameter in [u0, u1] whose point is closest to target (two-pass sampling)."""
    lo, hi = u0, u1
    best = u0
    for _ in range(2):
        uu = np.linspace(lo, hi, 200)
        curve = np.stack([np.polyval(c, uu) for c in coefs], axis=1)
        d2 = ((curve - target) ** 2).sum(axis=1)
        best = float(uu[int(d2.argmin())])
        step = (hi - lo) / 199.0
        lo, hi = max(u0, best - step), min(u1, best + step)
    return best


def curve_fix(pts, target, degree, keep, scale):
    """
    Place `target` on the curve that runs through the reference points `pts`.

    pts     : list of Vector, reference points (world space), at least 3
    target  : Vector, current position of the point to fix
    degree  : polynomial degree of the curve (clamped to len(pts) - 1)
    keep    : True  -> keep the point where it is along the curve (only snap it onto the curve)
              False -> average length: one average spacing beyond an end,
                       or halfway between its two neighbors
    scale   : multiplier for the average spacing (only used when extending, keep=False)

    Returns (new_position, message). Raises ValueError for unusable input.
    """
    n = len(pts)
    if n < 3:
        raise ValueError("Curve mode needs at least 3 other vertices.")

    fit = fit_line(pts)
    if fit is None:
        raise ValueError("The selected points are at the same location, no curve to follow.")
    c, d = fit

    # Order the reference points along the main direction of the chain
    ts = [(p - c).dot(d) for p in pts]
    idx = sorted(range(n), key=lambda i: ts[i])
    sp = [pts[i] for i in idx]
    st = [ts[i] for i in idx]

    # Curve parameter u: 0 at the first point, 1 at the last, proportional to chord length
    seg = [(sp[i + 1] - sp[i]).length for i in range(n - 1)]
    total = sum(seg)
    if total < 1e-9:
        raise ValueError("The selected points are at the same location, no curve to follow.")
    u = np.concatenate(([0.0], np.cumsum(seg))) / total

    # Polynomial curve P(u), one polynomial per coordinate
    arr = np.array([tuple(p) for p in sp], dtype=float)
    deg = max(1, min(int(degree), n - 1))
    coefs = [np.polyfit(u, arr[:, k], deg) for k in range(3)]

    tgt = np.array(tuple(target), dtype=float)
    du = 1.0 / (n - 1)  # average spacing in u units
    t_new = (target - c).dot(d)

    if t_new >= st[-1]:
        where = "beyond the end"
        if keep:
            u_new = _closest_u(coefs, tgt, 1.0 + 0.1 * du, 1.0 + 3.0 * du)
        else:
            u_new = 1.0 + du * scale
    elif t_new <= st[0]:
        where = "beyond the start"
        if keep:
            u_new = _closest_u(coefs, tgt, -3.0 * du, -0.1 * du)
        else:
            u_new = -du * scale
    else:
        where = "between its two neighbors"
        lo = max(i for i in range(n) if st[i] < t_new)
        hi = min(i for i in range(n) if st[i] > t_new)
        if keep:
            m = 0.1 * (u[hi] - u[lo])
            u_new = _closest_u(coefs, tgt, u[lo] + m, u[hi] - m)
        else:
            u_new = (u[lo] + u[hi]) / 2.0

    new = Vector([float(np.polyval(cf, u_new)) for cf in coefs])
    how = "stayed in place" if keep else "average length"
    return new, f"Curve fix: {where}, {how}, degree {deg}"


def extrude_calc(pts_chrono, curve, degree, scale):
    """
    Compute where a NEW point should go, continuing the chain past the last
    (most recently selected) reference point.

    pts_chrono : list of Vector, reference points in chronological (selection) order,
                 oldest -> newest. The chain is extended past pts_chrono[-1].
    curve      : True -> follow the fitted curve (needs >= 3 points)
                 False -> follow the fitted straight line (needs >= 2 points)
    degree     : polynomial degree for curve mode
    scale      : multiplier for the average spacing

    Returns new_position (Vector). Raises ValueError for unusable input.
    """
    n = len(pts_chrono)

    if curve:
        if n < 3:
            raise ValueError("Curve extrude needs at least 3 reference points.")
        seg = [(pts_chrono[i + 1] - pts_chrono[i]).length for i in range(n - 1)]
        total = sum(seg)
        if total < 1e-9:
            raise ValueError("The reference points are at the same location, no curve to follow.")
        u = np.concatenate(([0.0], np.cumsum(seg))) / total
        arr = np.array([tuple(p) for p in pts_chrono], dtype=float)
        deg = max(1, min(int(degree), n - 1))
        coefs = [np.polyfit(u, arr[:, k], deg) for k in range(3)]
        du = 1.0 / (n - 1)
        u_new = 1.0 + du * scale
        return Vector([float(np.polyval(cf, u_new)) for cf in coefs])

    else:
        if n < 2:
            raise ValueError("Line extrude needs at least 2 reference points.")
        fit = fit_line(pts_chrono)
        if fit is None:
            raise ValueError("The reference points are at the same location, no direction to follow.")
        c, d = fit
        if d.dot(pts_chrono[-1] - pts_chrono[0]) < 0:
            d.negate()
        spacing = sum((pts_chrono[i + 1] - pts_chrono[i]).length for i in range(n - 1)) / (n - 1)
        anchor = c + d * (pts_chrono[-1] - c).dot(d)
        return anchor + d * spacing * scale


# ----------------------------------------------------------------------------
# Operator: fix the last selected vertex
# ----------------------------------------------------------------------------

class MESH_OT_move_last_to_average(bpy.types.Operator):
    """Last selected vertex is fixed based on the other selected vertices"""
    bl_idname = "mesh.move_last_to_average"
    bl_label = "Move Last Vertex"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(
        name="Mode",
        items=[
            ('AUTO', "Smart (Auto)",
             "Fit a straight line through the other points. Beyond an end -> extend the line, "
             "between two points -> put it in the middle of its neighbors"),
            ('CURVE', "Curve Fix",
             "Like Smart, but follows the curve of the other points (needs at least 3 of them)"),
            ('CENTER', "Average Position",
             "Place the last vertex at the average position of the other points"),
        ],
        default='AUTO',
    )
    placement: bpy.props.EnumProperty(
        name="Placement",
        description="Smart and Curve Fix only: where along the line/curve the point ends up",
        items=[
            ('AVERAGE', "Average Distance",
             "Even spacing: one average spacing beyond an end, or halfway between its two neighbors"),
            ('KEEP', "Keep Distance (Direction Only)",
             "Keep the point's current position along the line/curve, only correct its direction "
             "by snapping it onto the line/curve"),
        ],
        default='AVERAGE',
    )
    degree: bpy.props.IntProperty(
        name="Curve Degree",
        description="Curve Fix only: 1 = straight line, 2 = simple arc, 3 = S-shaped curve "
                    "(limited to number of points - 1)",
        default=2,
        min=1,
        max=5,
    )
    spacing_scale: bpy.props.FloatProperty(
        name="Spacing Scale",
        description="Multiplier for the average spacing (Average Distance placement only)",
        default=1.0,
        min=0.0,
        soft_max=3.0,
    )
    window: bpy.props.IntProperty(
        name="Window",
        description="Use only the last N points (before the target) in selection order. 0 = use all selected points. "
                    "Keep 0 when fixing a vertex in the middle of the chain",
        default=0,
        min=0,
        soft_max=20,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and context.edit_object is not None

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        mw = obj.matrix_world

        active = bm.select_history.active
        if not isinstance(active, bmesh.types.BMVert) or not active.select:
            self.report(
                {'ERROR'},
                "No active vertex. Select vertices one by one (click), the last click is the target."
            )
            return {'CANCELLED'}

        others_all = [v for v in bm.verts if v.select and v != active]
        if not others_all:
            self.report({'ERROR'}, "Select at least one other vertex besides the last one.")
            return {'CANCELLED'}

        # Other selected vertices in selection order (oldest -> newest)
        history_others = [
            e for e in bm.select_history
            if isinstance(e, bmesh.types.BMVert) and e.select and e != active
        ]
        ordered_ok = len(history_others) == len(others_all)

        # Reference vertices (honor Window when selection order is available)
        note = ""
        if self.window > 0 and ordered_ok:
            used = history_others[-self.window:]
        else:
            used = others_all
            if self.window > 0:
                note = " (Window ignored: no selection order)"

        pts = [mw @ v.co for v in used]
        n = len(pts)
        target = mw @ active.co

        # ---------- Mode: average position ----------
        if self.mode == 'CENTER':
            new_world = sum(pts, Vector()) / n
            msg = f"Moved to the average of {n} vertices"

        # ---------- Mode: curve fix ----------
        elif self.mode == 'CURVE':
            try:
                new_world, msg = curve_fix(
                    pts, target, self.degree, self.placement == 'KEEP', self.spacing_scale
                )
            except ValueError as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}

        # ---------- Mode: smart (straight line) ----------
        else:
            if n < 2:
                self.report({'ERROR'}, "Smart mode needs at least 2 other vertices to define a line.")
                return {'CANCELLED'}

            fit = fit_line(pts)
            if fit is None:
                self.report({'ERROR'}, "The selected points are at the same location, no direction to follow.")
                return {'CANCELLED'}
            c, d = fit

            # Position of every reference point along the fitted line
            ts = [(p - c).dot(d) for p in pts]
            idx = sorted(range(n), key=lambda i: ts[i])
            sp = [pts[i] for i in idx]
            st = [ts[i] for i in idx]
            t_new = (target - c).dot(d)

            if self.placement == 'KEEP':
                # Preserve the point's position along the line, only remove its
                # perpendicular offset (direction correction, no distance change).
                if t_new >= st[-1]:
                    zone = "beyond the end"
                elif t_new <= st[0]:
                    zone = "beyond the start"
                else:
                    zone = "between its two neighbors"
                new_world = c + d * t_new
                msg = f"Snapped onto the line ({zone}), distance kept, direction corrected"
            else:
                spacing = sum((sp[i + 1] - sp[i]).length for i in range(n - 1)) / (n - 1)
                if t_new >= st[-1]:
                    new_world = c + d * (st[-1] + spacing * self.spacing_scale)
                    msg = f"Extended beyond the end, spacing = {spacing:.4f}"
                elif t_new <= st[0]:
                    new_world = c + d * (st[0] - spacing * self.spacing_scale)
                    msg = f"Extended beyond the start, spacing = {spacing:.4f}"
                else:
                    lo = max(i for i in range(n) if st[i] < t_new)
                    hi = min(i for i in range(n) if st[i] > t_new)
                    new_world = (sp[lo] + sp[hi]) / 2
                    gap = (sp[hi] - sp[lo]).length
                    msg = f"Placed between its two neighbors (gap = {gap:.4f}, each side = {gap / 2:.4f})"

        active.co = mw.inverted() @ new_world
        bmesh.update_edit_mesh(obj.data)
        self.report({'INFO'}, msg + note)
        return {'FINISHED'}


# ----------------------------------------------------------------------------
# Operator: extrude a new vertex, continuing the chain
# ----------------------------------------------------------------------------

class MESH_OT_extrude_average_chain(bpy.types.Operator):
    """Extrude a new vertex that continues the selected chain (line or curve)"""
    bl_idname = "mesh.extrude_average_chain"
    bl_label = "Extrude Chain Point"
    bl_options = {'REGISTER', 'UNDO'}

    curve: bpy.props.BoolProperty(
        name="Follow Curve",
        description="Follow the curve of the selected points instead of a straight line "
                    "(needs at least 3 selected points)",
        default=False,
    )
    degree: bpy.props.IntProperty(
        name="Curve Degree",
        description="Curve mode only: 1 = straight line, 2 = simple arc, 3 = S-shaped curve "
                    "(limited to number of points - 1)",
        default=2,
        min=1,
        max=5,
    )
    spacing_scale: bpy.props.FloatProperty(
        name="Spacing Scale",
        description="Multiplier for the average spacing between the selected points",
        default=1.0,
        min=0.0,
        soft_max=3.0,
    )
    window: bpy.props.IntProperty(
        name="Window",
        description="Use only the last N selected points (in selection order) as reference. "
                    "0 = use all selected points",
        default=0,
        min=0,
        soft_max=20,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and context.edit_object is not None

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        mw = obj.matrix_world
        mw_inv = mw.inverted()

        selected = [v for v in bm.verts if v.select]
        if len(selected) < 2:
            self.report({'ERROR'}, "Select at least 2 vertices (3 for curve), one by one (click), in order.")
            return {'CANCELLED'}

        ordered = [
            e for e in bm.select_history
            if isinstance(e, bmesh.types.BMVert) and e.select
        ]
        if len(ordered) != len(selected):
            self.report({'ERROR'}, "Some selected vertices have no selection order. Select them one by one (click).")
            return {'CANCELLED'}

        used = ordered[-self.window:] if self.window > 0 else ordered
        pts = [mw @ v.co for v in used]

        try:
            new_world = extrude_calc(pts, self.curve, self.degree, self.spacing_scale)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        last_vert = used[-1]
        ret = bmesh.ops.extrude_vert_indiv(bm, verts=[last_vert])
        new_vert = ret['verts'][0]
        new_vert.co = mw_inv @ new_world

        new_vert.select = True
        bm.select_history.add(new_vert)

        bmesh.update_edit_mesh(obj.data)
        kind = "curve" if self.curve else "line"
        self.report({'INFO'}, f"Extruded new point continuing the {kind}")
        return {'FINISHED'}


# ############################################################################
#
#   DRAW WITH VERTEX
#
# ############################################################################

SNAP_RADIUS_PX = 12.0

AXES = {
    'X': Vector((1.0, 0.0, 0.0)),
    'Y': Vector((0.0, 1.0, 0.0)),
    'Z': Vector((0.0, 0.0, 1.0)),
}


# ---------------------------------------------------------------------------
# Settings (shown in the sidebar panel, toggled live with hotkeys while drawing)
# ---------------------------------------------------------------------------

class DrawWithVertexSettings(bpy.types.PropertyGroup):
    plane_mode: bpy.props.EnumProperty(
        name="Plane",
        description="Which plane the clicked points are placed on",
        items=(
            ('VIEW', "View", "Plane faces the camera exactly"),
            ('AUTO', "Nearest Axis", "World axis plane closest to the view direction"),
            ('X', "X", "Lock to the plane perpendicular to X (YZ plane, side view)"),
            ('Y', "Y", "Lock to the plane perpendicular to Y (XZ plane, front view)"),
            ('Z', "Z", "Lock to the plane perpendicular to Z (XY plane, top view)"),
        ),
        default='VIEW',
    )
    use_grid_snap: bpy.props.BoolProperty(
        name="Snap to Grid",
        description="Snap clicked points to a grid on the drawing plane",
        default=False,
    )
    grid_size: bpy.props.FloatProperty(
        name="Grid Size",
        description="Spacing of the snapping grid",
        default=0.25, min=0.0001, soft_max=10.0, unit='LENGTH',
    )
    use_vertex_snap: bpy.props.BoolProperty(
        name="Snap to Vertices",
        description="Snap to existing vertices (the new face gets connected to them)",
        default=True,
    )
    angle_step: bpy.props.FloatProperty(
        name="Ctrl Angle Step",
        description="Angle increment used while holding Ctrl",
        default=math.radians(45.0), min=math.radians(1.0), max=math.radians(90.0),
        subtype='ANGLE',
    )
    show_fill: bpy.props.BoolProperty(
        name="Preview Fill",
        description="Show a filled preview of the face while drawing",
        default=True,
    )


def _settings(context):
    return context.scene.draw_with_vertex


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _uniform_shader():
    # Blender 4.x renamed the builtin shaders
    try:
        return gpu.shader.from_builtin('UNIFORM_COLOR')
    except ValueError:
        return gpu.shader.from_builtin('3D_UNIFORM_COLOR')


def _draw(shader, prim, coords, color, indices=None):
    batch = batch_for_shader(shader, prim, {"pos": coords}, indices=indices)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_callback(op, context):
    pts = list(op.points)
    preview = pts + [op.hover] if op.hover is not None and not op.hover_closes else pts
    if not preview:
        return

    shader = _uniform_shader()
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    if len(preview) >= 3 and _settings(context).show_fill:
        try:
            tris = geometry.tessellate_polygon([preview])
            _draw(shader, 'TRIS', preview, (1.0, 0.6, 0.1, 0.18), indices=tris)
        except Exception:
            pass

    if len(preview) >= 2:
        gpu.state.line_width_set(2.0)
        _draw(shader, 'LINE_STRIP', preview, (1.0, 0.6, 0.1, 1.0))
    if len(preview) >= 3:
        closing_alpha = 1.0 if op.hover_closes else 0.35
        _draw(shader, 'LINES', [preview[-1], preview[0]], (1.0, 0.6, 0.1, closing_alpha))

    if pts:
        gpu.state.point_size_set(8.0)
        _draw(shader, 'POINTS', pts, (1.0, 1.0, 1.0, 1.0))

    # Highlight the cursor point when it is snapped to something
    if op.hover is not None and op.hover_snapped:
        gpu.state.point_size_set(12.0)
        _draw(shader, 'POINTS', [op.hover], (0.2, 1.0, 0.4, 1.0))

    gpu.state.line_width_set(1.0)
    gpu.state.point_size_set(1.0)
    gpu.state.blend_set('NONE')


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class MESH_OT_draw_face_by_points(bpy.types.Operator):
    """Click points on the view plane, then press Enter to create a face from them"""
    bl_idname = "mesh.draw_face_by_points"
    bl_label = "Draw Face By Points"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH'
                and context.area is not None
                and context.area.type == 'VIEW_3D')

    # --- plane ---------------------------------------------------------------

    def _setup_plane(self, context):
        mode = _settings(context).plane_mode
        view_rot = context.region_data.view_rotation
        view_dir = view_rot @ Vector((0.0, 0.0, -1.0))

        if mode == 'AUTO':
            mode = max(AXES, key=lambda a: abs(view_dir.dot(AXES[a])))

        if mode in AXES:
            self.plane_no = AXES[mode].copy()
            self.plane_u, self.plane_v = {
                'X': (AXES['Y'], AXES['Z']),
                'Y': (AXES['X'], AXES['Z']),
                'Z': (AXES['X'], AXES['Y']),
            }[mode]
        else:
            self.plane_no = view_dir
            self.plane_u = view_rot @ Vector((1.0, 0.0, 0.0))
            self.plane_v = view_rot @ Vector((0.0, 1.0, 0.0))
        self.plane_label = mode

        # Plane goes through the first placed point, or the 3D cursor
        self.plane_co = self.points[0].copy() if self.points else context.scene.cursor.location.copy()

        # Grid origin: world origin for axis planes (so it lines up with the
        # world grid), the plane point for a free view plane
        if mode in AXES:
            self.grid_origin = self._project(Vector((0.0, 0.0, 0.0)))
        else:
            self.grid_origin = self.plane_co.copy()

        # Move already placed (non-welded) points onto the new plane
        for i, p in enumerate(self.points):
            if self.point_vidx[i] is None:
                self.points[i] = self._project(p)

    def _project(self, p):
        return p - self.plane_no * (p - self.plane_co).dot(self.plane_no)

    # --- snapping ------------------------------------------------------------

    def _mouse_to_plane(self, context):
        region = context.region
        rv3d = context.region_data
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, self.mouse)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, self.mouse)
        return geometry.intersect_line_plane(
            origin, origin + direction, self.plane_co, self.plane_no)

    def _nearest_screen_point(self, context, candidates):
        """Return (index, world_co) of the candidate closest to the mouse within the snap radius."""
        region = context.region
        rv3d = context.region_data
        mouse = Vector(self.mouse)
        best, best_d = None, SNAP_RADIUS_PX
        for key, co in candidates:
            p2d = view3d_utils.location_3d_to_region_2d(region, rv3d, co)
            if p2d is None:
                continue
            d = (p2d - mouse).length
            if d < best_d:
                best, best_d = (key, co), d
        return best

    def _snap_grid_2d(self, p, grid):
        d = p - self.grid_origin
        u = round(d.dot(self.plane_u) / grid) * grid
        v = round(d.dot(self.plane_v) / grid) * grid
        return self.grid_origin + self.plane_u * u + self.plane_v * v

    def _update_hover(self, context, ctrl):
        s = _settings(context)
        self.hover_vidx = None
        self.hover_snapped = False
        self.hover_closes = False

        # Clicking near the first point closes the shape
        if len(self.points) >= 3:
            if self._nearest_screen_point(context, [(0, self.points[0])]):
                self.hover = self.points[0]
                self.hover_snapped = True
                self.hover_closes = True
                return

        if s.use_vertex_snap:
            hit = self._nearest_screen_point(context, self.mesh_verts)
            if hit:
                self.hover_vidx, self.hover = hit
                self.hover_snapped = True
                return

        p = self._mouse_to_plane(context)
        if p is None:
            self.hover = None
            return

        if ctrl and self.points:
            # Constrain direction from the last point to angle_step increments
            last = self._project(self.points[-1])
            d = p - last
            du, dv = d.dot(self.plane_u), d.dot(self.plane_v)
            step = s.angle_step
            ang = round(math.atan2(dv, du) / step) * step
            direction = self.plane_u * math.cos(ang) + self.plane_v * math.sin(ang)
            length = d.dot(direction)
            if s.use_grid_snap:
                length = round(length / s.grid_size) * s.grid_size
            p = last + direction * length
            self.hover_snapped = True
        elif s.use_grid_snap:
            p = self._snap_grid_2d(p, s.grid_size)
            self.hover_snapped = True

        self.hover = p

    # --- UI ------------------------------------------------------------------

    def _update_header(self, context):
        s = _settings(context)
        on = lambda b: "ON" if b else "off"
        context.area.header_text_set(
            f"Draw Face: {len(self.points)} pt | Plane: {self.plane_label} "
            f"[X/Y/Z lock, again = view] | G grid: {on(s.use_grid_snap)} | "
            f"V vertex snap: {on(s.use_vertex_snap)} | F fill: {on(s.show_fill)} | "
            "Ctrl: angle | LMB add | Backspace undo | Enter/RMB finish | Esc cancel")

    def _finish(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        context.area.header_text_set(None)
        context.area.tag_redraw()

    # --- modal ---------------------------------------------------------------

    def invoke(self, context, event):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        mw = obj.matrix_world
        self.mesh_verts = [(v.index, mw @ v.co) for v in bm.verts if not v.hide]

        self.points = []
        self.point_vidx = []
        self.hover = None
        self.hover_vidx = None
        self.hover_snapped = False
        self.hover_closes = False
        self.mouse = (event.mouse_region_x, event.mouse_region_y)
        self._setup_plane(context)

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (self, context), 'WINDOW', 'POST_VIEW')
        context.window_manager.modal_handler_add(self)
        self._update_header(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()
        s = _settings(context)

        # Let the user orbit/pan/zoom while drawing (the plane stays fixed)
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
                          'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}

        if event.type == 'MOUSEMOVE':
            self.mouse = (event.mouse_region_x, event.mouse_region_y)
            self._update_hover(context, event.ctrl)
            return {'RUNNING_MODAL'}

        # Pressing/releasing Ctrl should update the preview without moving the mouse
        if event.type in {'LEFT_CTRL', 'RIGHT_CTRL'}:
            self._update_hover(context, event.value == 'PRESS')
            return {'RUNNING_MODAL'}

        if event.value != 'PRESS':
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE':
            self._update_hover(context, event.ctrl)
            if self.hover_closes:
                return self._complete(context)
            if self.hover is not None:
                if self.hover_vidx is not None and self.hover_vidx in self.point_vidx:
                    self.report({'WARNING'}, "That vertex is already part of this face")
                    return {'RUNNING_MODAL'}
                self.points.append(self.hover.copy())
                self.point_vidx.append(self.hover_vidx)
                if len(self.points) == 1:
                    # Re-anchor the plane on the first point
                    self._setup_plane(context)
                self._update_header(context)
            return {'RUNNING_MODAL'}

        if event.type == 'BACK_SPACE' or (event.type == 'Z' and event.ctrl):
            if self.points:
                self.points.pop()
                self.point_vidx.pop()
                self._update_hover(context, False)
                self._update_header(context)
            return {'RUNNING_MODAL'}

        if event.type in {'X', 'Y', 'Z'}:
            s.plane_mode = 'VIEW' if s.plane_mode == event.type else event.type
            self._setup_plane(context)
            self._update_hover(context, event.ctrl)
            self._update_header(context)
            return {'RUNNING_MODAL'}

        if event.type == 'G':
            s.use_grid_snap = not s.use_grid_snap
        elif event.type == 'V':
            s.use_vertex_snap = not s.use_vertex_snap
        elif event.type == 'F':
            s.show_fill = not s.show_fill
        if event.type in {'G', 'V', 'F'}:
            self._update_hover(context, event.ctrl)
            self._update_header(context)
            return {'RUNNING_MODAL'}

        if event.type in {'RET', 'NUMPAD_ENTER', 'SPACE', 'RIGHTMOUSE'}:
            return self._complete(context)

        if event.type == 'ESC':
            self._finish(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def _complete(self, context):
        self._finish(context)
        if len(self.points) < 3:
            self.report({'WARNING'}, "Need at least 3 points to make a face")
            return {'CANCELLED'}
        try:
            self._build_face(context)
        except ValueError as e:
            self.report({'ERROR'}, f"Could not create face: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

    def _build_face(self, context):
        obj = context.edit_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        to_local = obj.matrix_world.inverted()

        verts = []
        for p, vidx in zip(self.points, self.point_vidx):
            if vidx is not None:
                verts.append(bm.verts[vidx])  # weld to the existing vertex
            else:
                verts.append(bm.verts.new(to_local @ p))

        face = bm.faces.new(verts)

        for elem in (*bm.verts, *bm.edges, *bm.faces):
            elem.select = False

        face.normal_update()
        # Make the face point toward the viewer
        view_dir = context.region_data.view_rotation @ Vector((0.0, 0.0, -1.0))
        if face.normal.dot(to_local.to_3x3() @ -view_dir) < 0.0:
            face.normal_flip()

        face.select = True
        for v in verts:
            v.select = True
        bm.select_flush(True)
        bmesh.update_edit_mesh(me)


# ############################################################################
#
#   UI: N Panel > Tool > Vertex Tools
#
# ############################################################################

class VIEW3D_PT_vertex_tools(bpy.types.Panel):
    bl_label = "Vertex Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        pass


class VIEW3D_PT_average_vertex(bpy.types.Panel):
    bl_label = "Average Vertex"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_parent_id = "VIEW3D_PT_vertex_tools"

    def draw(self, context):
        layout = self.layout
        fix_id = MESH_OT_move_last_to_average.bl_idname
        extrude_id = MESH_OT_extrude_average_chain.bl_idname

        layout.label(text="Fix Selected Vertex:")
        col = layout.column(align=True)
        op = col.operator(fix_id, text="Smart: Average Distance", icon='MODIFIER')
        op.mode = 'AUTO'
        op.placement = 'AVERAGE'
        op = col.operator(fix_id, text="Smart: Keep Distance", icon='SNAP_NORMAL')
        op.mode = 'AUTO'
        op.placement = 'KEEP'

        col = layout.column(align=True)
        op = col.operator(fix_id, text="Curve: Average Distance", icon='CURVE_DATA')
        op.mode = 'CURVE'
        op.placement = 'AVERAGE'
        op = col.operator(fix_id, text="Curve: Keep Distance", icon='PINNED')
        op.mode = 'CURVE'
        op.placement = 'KEEP'

        op = layout.operator(fix_id, text="Move to Average", icon='SNAP_MIDPOINT')
        op.mode = 'CENTER'

        layout.separator()
        layout.label(text="Extrude New Vertex:")
        col = layout.column(align=True)
        op = col.operator(extrude_id, text="Extrude Along Line", icon='FORWARD')
        op.curve = False
        op = col.operator(extrude_id, text="Extrude Along Curve", icon='SPHERECURVE')
        op.curve = True


class VIEW3D_PT_draw_with_vertex(bpy.types.Panel):
    bl_label = "Draw With Vertex"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_parent_id = "VIEW3D_PT_vertex_tools"

    def draw(self, context):
        s = _settings(context)
        layout = self.layout
        layout.operator(MESH_OT_draw_face_by_points.bl_idname, icon='GREASEPENCIL')

        layout.label(text="Plane:")
        row = layout.row(align=True)
        row.prop(s, "plane_mode", expand=True)

        col = layout.column(align=True)
        col.prop(s, "use_grid_snap", icon='SNAP_GRID')
        sub = col.row()
        sub.active = s.use_grid_snap
        sub.prop(s, "grid_size")

        col = layout.column(align=True)
        col.prop(s, "use_vertex_snap", icon='SNAP_VERTEX')
        col.prop(s, "angle_step")
        col.prop(s, "show_fill")

        layout.label(text="Plane passes through the 3D cursor", icon='INFO')


def average_vertex_menu_func(self, context):
    fix_id = MESH_OT_move_last_to_average.bl_idname
    extrude_id = MESH_OT_extrude_average_chain.bl_idname
    self.layout.separator()
    op = self.layout.operator(fix_id, text="Smart Fix Last Vertex: Average Distance")
    op.mode = 'AUTO'
    op.placement = 'AVERAGE'
    op = self.layout.operator(fix_id, text="Smart Fix Last Vertex: Keep Distance")
    op.mode = 'AUTO'
    op.placement = 'KEEP'
    op = self.layout.operator(fix_id, text="Curve Fix Last Vertex: Average Distance")
    op.mode = 'CURVE'
    op.placement = 'AVERAGE'
    op = self.layout.operator(fix_id, text="Curve Fix Last Vertex: Keep Distance")
    op.mode = 'CURVE'
    op.placement = 'KEEP'
    op = self.layout.operator(fix_id, text="Move Last Vertex to Average")
    op.mode = 'CENTER'
    self.layout.separator()
    op = self.layout.operator(extrude_id, text="Extrude Chain Point Along Line")
    op.curve = False
    op = self.layout.operator(extrude_id, text="Extrude Chain Point Along Curve")
    op.curve = True


def draw_with_vertex_menu_func(self, context):
    self.layout.separator()
    self.layout.operator(MESH_OT_draw_face_by_points.bl_idname, icon='GREASEPENCIL')


# ############################################################################
#
#   Registration
#
# ############################################################################

classes = (
    MESH_OT_move_last_to_average,
    MESH_OT_extrude_average_chain,
    DrawWithVertexSettings,
    MESH_OT_draw_face_by_points,
    VIEW3D_PT_vertex_tools,
    VIEW3D_PT_average_vertex,
    VIEW3D_PT_draw_with_vertex,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.draw_with_vertex = bpy.props.PointerProperty(type=DrawWithVertexSettings)
    bpy.types.VIEW3D_MT_edit_mesh_vertices.append(average_vertex_menu_func)
    bpy.types.VIEW3D_MT_edit_mesh.append(draw_with_vertex_menu_func)


def unregister():
    bpy.types.VIEW3D_MT_edit_mesh.remove(draw_with_vertex_menu_func)
    bpy.types.VIEW3D_MT_edit_mesh_vertices.remove(average_vertex_menu_func)
    del bpy.types.Scene.draw_with_vertex
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
