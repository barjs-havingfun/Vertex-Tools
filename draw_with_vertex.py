bl_info = {
    "name": "Draw With Vertex",
    "author": "baris",
    "version": (0, 2, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Edit Mode > Sidebar (N) > Edit tab, or Mesh menu",
    "description": "Click points in the viewport to build a face on the view plane",
    "category": "Mesh",
}

import math

import bpy
import bmesh
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from mathutils import Vector, geometry


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


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class VIEW3D_PT_draw_with_vertex(bpy.types.Panel):
    bl_label = "Draw With Vertex"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Edit"
    bl_context = "mesh_edit"

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


def _menu_func(self, context):
    self.layout.separator()
    self.layout.operator(MESH_OT_draw_face_by_points.bl_idname, icon='GREASEPENCIL')


classes = (DrawWithVertexSettings, MESH_OT_draw_face_by_points, VIEW3D_PT_draw_with_vertex)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.draw_with_vertex = bpy.props.PointerProperty(type=DrawWithVertexSettings)
    bpy.types.VIEW3D_MT_edit_mesh.append(_menu_func)


def unregister():
    bpy.types.VIEW3D_MT_edit_mesh.remove(_menu_func)
    del bpy.types.Scene.draw_with_vertex
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
