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
from mathutils import Matrix, Vector, geometry, kdtree


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


def chain_fix(pts, curve, degree, even):
    """
    New positions for a whole chain of points, fitted to one line or curve.

    pts    : list of Vector, the chain in order (world space), at least 3
    curve  : True -> polynomial curve, False -> straight line
    degree : polynomial degree for curve mode
    even   : True  -> evenly spaced from the first to the last point
             False -> every point keeps its place along the fit, only snapped onto it

    Returns list of Vector (same order). Raises ValueError for unusable input.
    """
    n = len(pts)
    if n < 3:
        raise ValueError("Select at least 3 vertices for a chain.")

    if not curve:
        fit = fit_line(pts)
        if fit is None:
            raise ValueError("The selected points are at the same location, no direction to follow.")
        c, d = fit
        proj = [c + d * (p - c).dot(d) for p in pts]
        if not even:
            return proj
        return [proj[0].lerp(proj[-1], i / (n - 1)) for i in range(n)]

    # Curve parameter u: 0 at the first point, 1 at the last, proportional to chord length
    seg = [(pts[i + 1] - pts[i]).length for i in range(n - 1)]
    total = sum(seg)
    if total < 1e-9:
        raise ValueError("The selected points are at the same location, no curve to follow.")
    u = np.concatenate(([0.0], np.cumsum(seg))) / total
    arr = np.array([tuple(p) for p in pts], dtype=float)
    deg = max(1, min(int(degree), n - 1))
    coefs = [np.polyfit(u, arr[:, k], deg) for k in range(3)]

    if even:
        # Equal arc length steps along the curve from u = 0 to u = 1
        uu = np.linspace(0.0, 1.0, 2001)
        curve_pts = np.stack([np.polyval(cf, uu) for cf in coefs], axis=1)
        cum = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(curve_pts, axis=0), axis=1))))
        u_new = np.interp(np.linspace(0.0, cum[-1], n), cum, uu)
    else:
        du = 1.0 / (n - 1)
        u_new = [_closest_u(coefs, arr[i], u[i] - du / 2, u[i] + du / 2) for i in range(n)]

    return [Vector([float(np.polyval(cf, ui)) for cf in coefs]) for ui in u_new]


def selected_chain(bm):
    """
    The selected vertices as an ordered chain: selection order when every vertex has one,
    otherwise followed along the selected edges (must be one open path).
    Returns list of BMVert, or None.
    """
    selected = [v for v in bm.verts if v.select]
    ordered = [
        e for e in bm.select_history
        if isinstance(e, bmesh.types.BMVert) and e.select
    ]
    if len(ordered) == len(selected):
        return ordered

    sel = set(selected)
    links = {v: [e.other_vert(v) for e in v.link_edges if e.other_vert(v) in sel] for v in selected}
    ends = [v for v in selected if len(links[v]) == 1]
    if len(ends) != 2 or any(len(nb) > 2 for nb in links.values()):
        return None

    chain, prev = [ends[0]], None
    while len(chain) < len(selected):
        nxt = [v for v in links[chain[-1]] if v is not prev]
        if not nxt:
            return None
        prev = chain[-1]
        chain.append(nxt[0])
    return chain


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


# ----------------------------------------------------------------------------
# Operator: fix the whole chain at once
# ----------------------------------------------------------------------------

class MESH_OT_fix_vertex_chain(bpy.types.Operator):
    """Fit a line or curve through the whole selected chain and move every vertex onto it"""
    bl_idname = "mesh.fix_vertex_chain"
    bl_label = "Fix Whole Chain"
    bl_options = {'REGISTER', 'UNDO'}

    curve: bpy.props.BoolProperty(
        name="Follow Curve",
        description="Fit a curve instead of a straight line",
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
    placement: bpy.props.EnumProperty(
        name="Placement",
        items=[
            ('AVERAGE', "Even Spacing",
             "Space all points evenly from the first to the last point"),
            ('KEEP', "Keep Distance (Direction Only)",
             "Keep each point's position along the line/curve, only snap it onto the line/curve"),
        ],
        default='AVERAGE',
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and context.edit_object is not None

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        mw = obj.matrix_world

        chain = selected_chain(bm)
        if chain is None:
            self.report(
                {'ERROR'},
                "Can't find the chain order. Click the vertices one by one, "
                "or select one connected path of edges."
            )
            return {'CANCELLED'}

        pts = [mw @ v.co for v in chain]
        try:
            new = chain_fix(pts, self.curve, self.degree, self.placement == 'AVERAGE')
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        mw_inv = mw.inverted()
        for v, p in zip(chain, new):
            v.co = mw_inv @ p

        bmesh.update_edit_mesh(obj.data)
        kind = "curve" if self.curve else "line"
        how = "evenly spaced" if self.placement == 'AVERAGE' else "snapped"
        self.report({'INFO'}, f"Fixed {len(chain)} vertices onto the {kind}, {how}")
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
        description="Snap to existing vertices",
        default=True,
    )
    use_edge_snap: bpy.props.BoolProperty(
        name="Snap to Edges",
        description="Snap onto existing edges (and their midpoints). With Merge on, the edge "
                    "is split there so the new face connects to it",
        default=True,
    )
    use_merge: bpy.props.BoolProperty(
        name="Merge",
        description="Points that sit on an existing vertex are merged with it, so the new face "
                    "is really connected to the mesh. Off = a separate vertex is created on top",
        default=True,
    )
    merge_distance: bpy.props.FloatProperty(
        name="Merge Distance",
        description="Points closer than this to an existing vertex are merged with it "
                    "(also catches grid / angle snapped points that land on a vertex)",
        default=0.001, min=0.0, soft_max=0.1, unit='LENGTH',
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


def _dist_to_segment(p, a, b):
    t = geometry.intersect_point_line(p, a, b)[1]
    return (p - a.lerp(b, min(max(t, 0.0), 1.0))).length


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

    # Highlight the edge the cursor is snapped to
    if op.hover is not None and op.hover_edge_co is not None:
        gpu.state.line_width_set(3.0)
        _draw(shader, 'LINES', list(op.hover_edge_co), (1.0, 0.3, 0.9, 1.0))

    if pts:
        gpu.state.point_size_set(8.0)
        _draw(shader, 'POINTS', pts, (1.0, 1.0, 1.0, 1.0))

    # Highlight the cursor point: blue = will merge with an existing vertex / edge,
    # green = snapped to something
    on_mesh = op.hover_vidx is not None or op.hover_edge is not None
    if op.hover is not None and on_mesh and _settings(context).use_merge:
        gpu.state.point_size_set(14.0)
        _draw(shader, 'POINTS', [op.hover], (0.2, 0.6, 1.0, 1.0))
    elif op.hover is not None and op.hover_snapped:
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

        # Move already placed free points (not on a vertex or edge) onto the new plane
        for i, p in enumerate(self.points):
            if self.point_vidx[i] is None and self.point_edge[i] is None:
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

    def _nearest_edge(self, context):
        """Return (edge_index, (a, b), world_co) of the edge closest to the mouse within the
        snap radius, or None. Snaps to the edge midpoint when the mouse is near it."""
        region = context.region
        rv3d = context.region_data
        mouse2d = Vector(self.mouse)
        mouse = mouse2d.to_3d()
        best, best_d = None, SNAP_RADIUS_PX
        for key, a, b in self.mesh_edges:
            a2d = view3d_utils.location_3d_to_region_2d(region, rv3d, a)
            b2d = view3d_utils.location_3d_to_region_2d(region, rv3d, b)
            if a2d is None or b2d is None or (a2d - b2d).length < 1e-6:
                continue
            closest, t = geometry.intersect_point_line(mouse, a2d.to_3d(), b2d.to_3d())
            if not 0.0 <= t <= 1.0:
                continue
            d = (closest - mouse).length
            if d < best_d:
                best, best_d = (key, a, b, t), d
        if best is None:
            return None

        key, a, b, t = best
        mid = (a + b) / 2
        mid2d = view3d_utils.location_3d_to_region_2d(region, rv3d, mid)
        if mid2d is not None and (mid2d - mouse2d).length < SNAP_RADIUS_PX:
            return key, (a, b), mid

        # Exact 3D point on the edge under the mouse ray (screen t is off in perspective)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, self.mouse)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, self.mouse)
        hit = geometry.intersect_line_line(origin, origin + direction, a, b)
        if hit is not None:
            t = geometry.intersect_point_line(hit[1], a, b)[1]
        return key, (a, b), a.lerp(b, min(max(t, 0.0), 1.0))

    def _snap_grid_2d(self, p, grid):
        d = p - self.grid_origin
        u = round(d.dot(self.plane_u) / grid) * grid
        v = round(d.dot(self.plane_v) / grid) * grid
        return self.grid_origin + self.plane_u * u + self.plane_v * v

    def _update_hover(self, context, ctrl):
        s = _settings(context)
        self.hover_vidx = None
        self.hover_edge = None
        self.hover_edge_co = None
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

        if s.use_edge_snap:
            hit = self._nearest_edge(context)
            if hit:
                self.hover_edge, self.hover_edge_co, self.hover = hit
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

        # A point that lands on an existing vertex (e.g. via grid snap) sits on it
        if self.mesh_verts:
            co, idx, dist = self.kd.find(p)
            if dist <= s.merge_distance:
                self.hover_vidx = self.mesh_verts[idx][0]
                p = co
                self.hover_snapped = True

        self.hover = p

    # --- UI ------------------------------------------------------------------

    def _update_header(self, context):
        s = _settings(context)
        on = lambda b: "ON" if b else "off"
        context.area.header_text_set(
            f"Draw Face: {len(self.points)} pt | Plane: {self.plane_label} "
            f"[X/Y/Z lock, again = view] | G grid: {on(s.use_grid_snap)} | "
            f"V vertex snap: {on(s.use_vertex_snap)} | E edge snap: {on(s.use_edge_snap)} | "
            f"M merge: {on(s.use_merge)} | "
            f"F fill: {on(s.show_fill)} | "
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
        # Indices of freshly created verts (previous face, extrude) can be stale
        bm.verts.index_update()
        bm.edges.index_update()
        self.mesh_verts = [(v.index, mw @ v.co) for v in bm.verts if not v.hide]
        self.mesh_edges = [(e.index, mw @ e.verts[0].co, mw @ e.verts[1].co)
                           for e in bm.edges if not e.hide]

        self.kd = kdtree.KDTree(len(self.mesh_verts))
        for i, (_, co) in enumerate(self.mesh_verts):
            self.kd.insert(co, i)
        self.kd.balance()

        self.points = []
        self.point_vidx = []
        self.point_edge = []
        self.hover = None
        self.hover_vidx = None
        self.hover_edge = None
        self.hover_edge_co = None
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
                if (s.use_merge and self.hover_vidx is not None
                        and self.hover_vidx in self.point_vidx):
                    self.report({'WARNING'}, "That vertex is already part of this face")
                    return {'RUNNING_MODAL'}
                self.points.append(self.hover.copy())
                self.point_vidx.append(self.hover_vidx)
                self.point_edge.append(self.hover_edge)
                if len(self.points) == 1:
                    # Re-anchor the plane on the first point
                    self._setup_plane(context)
                self._update_header(context)
            return {'RUNNING_MODAL'}

        if event.type == 'BACK_SPACE' or (event.type == 'Z' and event.ctrl):
            if self.points:
                self.points.pop()
                self.point_vidx.pop()
                self.point_edge.pop()
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
        elif event.type == 'E':
            s.use_edge_snap = not s.use_edge_snap
        elif event.type == 'M':
            s.use_merge = not s.use_merge
        elif event.type == 'F':
            s.show_fill = not s.show_fill
        if event.type in {'G', 'V', 'E', 'M', 'F'}:
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
        bm.edges.ensure_lookup_table()
        to_local = obj.matrix_world.inverted()

        use_merge = _settings(context).use_merge
        if use_merge:
            merged = [i for i in self.point_vidx if i is not None]
            if len(merged) != len(set(merged)):
                raise ValueError("two points merge into the same vertex")

        # Look up the existing vertices and edges first: creating or splitting
        # invalidates the lookup tables
        verts = [bm.verts[vidx] if use_merge and vidx is not None else None
                 for vidx in self.point_vidx]
        edges = [bm.edges[eidx] if use_merge and eidx is not None else None
                 for eidx in self.point_edge]

        # Split snapped edges, so the new vertex is shared with the edge (and its faces)
        pieces = {}  # original edge -> its pieces after splitting (several points on one edge)
        for i, e in enumerate(edges):
            if e is None:
                continue
            co = to_local @ self.points[i]
            parts = pieces.setdefault(e, [e])
            part = min(parts, key=lambda pe: _dist_to_segment(co, pe.verts[0].co, pe.verts[1].co))
            v0 = part.verts[0]
            length = part.calc_length()
            fac = (co - v0.co).length / length if length > 0.0 else 0.5
            new_edge, new_vert = bmesh.utils.edge_split(part, v0, min(max(fac, 0.0), 1.0))
            new_vert.co = co
            parts.append(new_edge)
            verts[i] = new_vert

        for i, p in enumerate(self.points):
            if verts[i] is None:
                verts[i] = bm.verts.new(to_local @ p)

        # Reuses existing edges between merged vertices, so the face is connected
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
#   FACE PROJECTION
#
# ############################################################################

def selection_plane(bm, mw):
    """
    Plane of the selected elements in world space.

    Selected faces -> their (area weighted) normal.
    Otherwise      -> best-fit plane through the selected vertices
                      (3 vertices, 2 edges, or more).

    Returns (center, unit normal, from_faces). Raises ValueError for unusable input.
    """
    verts = [v for v in bm.verts if v.select]
    if len(verts) < 3:
        raise ValueError("Select 3 vertices, 2 edges or a face.")
    pts = [mw @ v.co for v in verts]
    center = sum(pts, Vector()) / len(pts)

    faces = [f for f in bm.faces if f.select]
    if faces:
        nmat = mw.inverted_safe().transposed().to_3x3()
        n = sum(((nmat @ f.normal).normalized() * f.calc_area() for f in faces), Vector())
        if n.length > 1e-9:
            return center, n.normalized(), True

    arr = np.array([tuple(p - center) for p in pts], dtype=float)
    _, s, vt = np.linalg.svd(arr, full_matrices=False)
    if s[0] < 1e-9 or s[1] < 1e-6 * s[0]:
        raise ValueError("The selected points are on one line, they don't define a plane.")
    return center, Vector(vt[2].tolist()).normalized(), False


class VIEW3D_OT_align_view_to_selection(bpy.types.Operator):
    """Look straight at the plane of the selection (3 vertices, 2 edges or a face)"""
    bl_idname = "view3d.align_view_to_selection"
    bl_label = "Align View to Selection"
    bl_options = {'REGISTER', 'UNDO'}

    roll: bpy.props.EnumProperty(
        name="Roll",
        description="How the view is turned around the viewing direction",
        items=[
            ('WORLD', "World Up",
             "World Z points up on screen, like the Front / Side views "
             "(flat planes: world Y up, like the Top view)"),
            ('EDGE', "Edge Horizontal",
             "The first two clicked vertices (or the longest selected edge) lie horizontal on screen"),
            ('VIEW', "Keep Current",
             "Keep the current screen up direction as much as possible"),
        ],
        default='WORLD',
    )
    flip: bpy.props.BoolProperty(
        name="Flip",
        description="Look at the plane from the other side",
        default=False,
    )
    center: bpy.props.BoolProperty(
        name="Center View",
        description="Center the view on the selection",
        default=True,
    )
    ortho: bpy.props.BoolProperty(
        name="Orthographic",
        description="Switch to an orthographic view (true projection, no perspective)",
        default=True,
    )
    set_cursor: bpy.props.BoolProperty(
        name="Move 3D Cursor",
        description="Move the 3D cursor to the selection and rotate it to the plane. "
                    "Draw With Vertex (View plane) then draws exactly on this plane",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH'
                and context.space_data is not None
                and context.space_data.type == 'VIEW_3D')

    def _screen_axes(self, bm, mw, n, rv3d):
        """Screen right (x) and up (y) directions on the plane with normal n, from the Roll option."""
        def on_plane(d):
            d = d - n * d.dot(n)
            return d.normalized() if d.length > 1e-3 else None

        world_up = on_plane(Vector((0.0, 0.0, 1.0)))
        if world_up is None:  # flat plane: like the Top view, world Y up
            world_up = on_plane(Vector((0.0, 1.0, 0.0)))

        if self.roll == 'EDGE':
            clicked = [e for e in bm.select_history if isinstance(e, bmesh.types.BMVert) and e.select]
            edges = [e for e in bm.edges if e.select]
            x = None
            if len(clicked) >= 2:
                x = on_plane(mw @ clicked[1].co - mw @ clicked[0].co)
            elif edges:
                v0, v1 = max(edges, key=lambda e: e.calc_length()).verts
                x = on_plane(mw @ v1.co - mw @ v0.co)
            if x is not None:
                y = n.cross(x)
                # Keep it upright: don't let the world end up upside down
                if world_up is not None and y.dot(world_up) < 0.0:
                    x, y = -x, -y
                return x, y

        y = None
        if self.roll == 'VIEW':
            y = on_plane(rv3d.view_rotation @ Vector((0.0, 1.0, 0.0)))
        if y is None:
            y = world_up
        return y.cross(n), y

    def execute(self, context):
        obj = context.edit_object
        bm = bmesh.from_edit_mesh(obj.data)
        rv3d = context.space_data.region_3d  # also works from the sidebar

        try:
            center, n, from_faces = selection_plane(bm, obj.matrix_world)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Faces: look at their front. Vertices / edges: stay on the side we look from now
        toward_viewer = rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))
        if not from_faces and n.dot(toward_viewer) < 0.0:
            n = -n
        if self.flip:
            n = -n

        rot = Matrix((*self._screen_axes(bm, obj.matrix_world, n, rv3d), n)).transposed().to_quaternion()

        if rv3d.view_perspective == 'CAMERA':
            rv3d.view_perspective = 'PERSP'
        rv3d.view_rotation = rot
        if self.center:
            rv3d.view_location = center
        if self.ortho:
            rv3d.view_perspective = 'ORTHO'

        if self.set_cursor:
            m = rot.to_matrix().to_4x4()
            m.translation = center
            context.scene.cursor.matrix = m

        what = "faces" if from_faces else "vertices"
        self.report({'INFO'}, f"View aligned to the plane of the selected {what}")
        return {'FINISHED'}


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
        layout.label(text="Fix Whole Chain:")
        col = layout.column(align=True)
        op = col.operator(MESH_OT_fix_vertex_chain.bl_idname, text="Chain: Even Along Line", icon='IPO_LINEAR')
        op.curve = False
        op = col.operator(MESH_OT_fix_vertex_chain.bl_idname, text="Chain: Even Along Curve", icon='IPO_BEZIER')
        op.curve = True

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
        col.prop(s, "use_edge_snap", icon='SNAP_EDGE')
        col.prop(s, "use_merge", icon='AUTOMERGE_ON' if s.use_merge else 'AUTOMERGE_OFF')
        sub = col.row()
        sub.active = s.use_merge
        sub.prop(s, "merge_distance")

        col = layout.column(align=True)
        col.prop(s, "angle_step")
        col.prop(s, "show_fill")

        layout.label(text="Plane passes through the 3D cursor", icon='INFO')


class VIEW3D_PT_face_projection(bpy.types.Panel):
    bl_label = "Face Projection"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_parent_id = "VIEW3D_PT_vertex_tools"

    def draw(self, context):
        layout = self.layout
        align_id = VIEW3D_OT_align_view_to_selection.bl_idname

        layout.label(text="3 vertices, 2 edges or a face:")
        col = layout.column(align=True)
        op = col.operator(align_id, text="Align View to Selection", icon='VIEW_ORTHO')
        op.set_cursor = False
        op = col.operator(align_id, text="Align View + Cursor (Draw)", icon='PIVOT_CURSOR')
        op.set_cursor = True


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
    op = self.layout.operator(MESH_OT_fix_vertex_chain.bl_idname, text="Fix Whole Chain Along Line")
    op.curve = False
    op = self.layout.operator(MESH_OT_fix_vertex_chain.bl_idname, text="Fix Whole Chain Along Curve")
    op.curve = True
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
    MESH_OT_fix_vertex_chain,
    DrawWithVertexSettings,
    MESH_OT_draw_face_by_points,
    VIEW3D_PT_vertex_tools,
    VIEW3D_PT_average_vertex,
    VIEW3D_PT_draw_with_vertex,
    VIEW3D_OT_align_view_to_selection,
    VIEW3D_PT_face_projection,
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
