# Development Log — Vertex Tools

A day-by-day record of the work on the Vertex Tools Blender add-on
(`vertex_tools.py`), in the order it was done.

---

## 2026-10-07 (Wednesday)

**Summary:** Merged two separate scripts into one add-on with its own
sidebar tab, and grew it from 2 tools to 3
sections. Average Vertex got circle fitting and Preview & Apply. Draw With
Vertex got merging, shapes and snapping, plus Draw on Face. The new Face
Projection section aligns the view to a plane.
Version went to **3.3.0**.

### 1. Merging the two scripts
- Compared `move_last_to_average.py` and `draw_with_vertex.py`.
- Merged them into one file, `vertex_tools.py`, with two separate
  sections, **Average Vertex** and **Draw with Vertex**, under
  **N Panel > Vertex Tools**.
- Wrote one combined README for both tools.

### 2. Merge option for Draw With Vertex
- Added **Merge**: points snapped onto existing vertices are merged with
  them, so drawn faces really connect to the mesh.
- Installed the add-on into Blender 5.2 to replace the old version.
- **Bug fixed:** an `IndexError` in `_build_face` when merging into an
  existing vertex (stale vertex lookup table).

### 3. Edge snapping, Fix Whole Chain, Face Projection
- **Edge snapping:** snap onto edges and their midpoints. With Merge on,
  the edge is split there.
- **Fix Whole Chain:** spaces an entire vertex chain evenly along a line
  or curve.
- **Face Projection** (new third section): align the view straight onto
  the plane of 3 vertices, 2 edges or 1 face.
- **Fix:** the aligned view's roll looked "weird". It's now chosen so the
  selection sits upright on screen.

### 4. Feature round from the idea list
Picked features #3–9 and #11–13 from the proposal list. All were built,
and 32 headless checks passed in Blender 5.2.
- **#3 Edges Only (`P`):** open paths or closed edge loops, no face.
- **#4 Shapes:** Rectangle (2 clicks) and Circle / polygon (any number of
  sides, `R` / `C`, `+` / `-`).
- **#5 Surface plane (`S`):** draw directly on the surface under the
  mouse, with Surface Offset.
- **#6 Count:** extrude several chain points at once.
- **#7 Circle fit:** for Fix Last, Chain (arc and **Full Circle**) and
  Extrude. The old Line and Curve fits were kept.
- **#8 Preview & Apply:** ghost preview of the result. The Preview
  button turns into Cancel, and clicking anywhere outside also cancels.
- **#9 Flatten to Plane:** moves the selection onto its best-fit plane.
- **#11 Back to Previous View:** a multi-step view history.
- **#12 Align + Draw:** align the view, place the cursor and start
  drawing, in one click.
- **#13 Shift+Q menu:** a three-column menu with every action (Shift+Q is
  unused in Blender's Edit Mode keymap).
- Version **3.0.0**.

### 5. Panel layout iterations
- Explained the **Window** option in Preview & Apply.
- Made **Preview & Apply** a collapsible sub-panel.
- Tried a compact layout for the whole tab. It was **rejected** as too
  cramped and reverted. Kept: the collapsible Preview & Apply, and the
  compact snap icon row in Draw With Vertex.
- Restored the Window option, which had been removed by mistake.
- Audited the code against everything agreed so far. Everything was
  intact except the shortening idea, which was dropped on purpose.

### 6. Draw on Face
- New **Draw on Face** button: click a face and draw a shape flat on its
  plane. Clicking empty space gives an error that points you to Draw.
- **Face Method** in the bottom-left panel:
  - **Cut In** (default)
  - **Replace (leave gap)**
  - **Auto-Bridge**
- Merging works against the face's own vertices and edges, so shapes can
  share edges with the outer face.

### 7. Auto-Bridge and visibility fixes
- **Auto-Bridge rewritten:** it connects points to their *nearest*
  partners (no more faces stretching to far corners), joins triangles
  into quads, and checks that the result never overlaps.
- **Snap only to what you can see:** hidden vertices and edges are
  ignored unless X-ray is on.
- **Auto-Bridge options:** Attach Mode (Nearest / Even / Blender
  Bridge), a Twist slider and a Quad Angle slider. If the chosen setting
  would overlap, it automatically falls back to one that works.
- Explained **Flatten to Plane**.

### 8. README: Draw on Face vs. the Knife tool
- Added a comparison table: where Draw on Face is better (exact shapes,
  flattening, grid, face methods, Auto-Bridge) and where the Knife is
  better (multi-face cuts, open cuts, Cut Through, freeform paths).

---

## 2026-10-08 (Thursday)

**Summary:** Added a third draw mode, **Draw for Bool**: draw a shape,
pull it in or out by hand, and get a live, editable Boolean cutter or
adder object. Then added a symmetric (both directions) pull, a
bottom-left options panel and CAD-style **Align Snap**.
Version **3.4.0**.

### 1. Review and design of Draw for Bool
- Reviewed yesterday's session and `vertex_tools.py` to plan the new mode.
- Agreed on the design:
  - **Cutter type:** a separate object with a live Boolean modifier,
    started from Edit Mode on the part.
  - **Buttons:** Auto / Cut / Extrude. The pull direction is never
    restricted, so you can, for example, fill the part of a shape that
    hangs over the face's edge.
  - **Start:** the first click on a face uses that face's plane.
    Otherwise the shape goes on the view plane through the 3D cursor.

### 2. Draw for Bool implemented
- **Refactor:** moved face picking into a shared base used by both Draw
  on Face and Draw for Bool.
- **Pulling:** move the mouse to set the depth live (Ctrl snaps it to the
  grid size, Tab switches the mode). Auto cuts when pushed in and adds
  when pulled out.
- **On confirm:** you're put into Edit Mode on the cutter with its far
  cap selected, so `G` changes the depth and `S` angles the walls.
- **New Bool Cutters panel:**
  - switch Difference / Union / Intersect
  - change the solver
  - **Edit Cutter**, **Back to Mesh**, **Apply Bool** and **Apply All
    Bools**
- **Bug found by testing and fixed:** Extrude pulled inward left a thin
  bump above the surface. The cutter's base is now placed per operation.
- **Fix:** the header unit display failed on Blender 5.2's API.
- README section added.

### 3. Both Directions, bottom-left panel, Align Snap
- **Bottom-left panel** for Draw for Bool: Mode, exact Depth, and
  **Both Directions**. Changing a value rebuilds the cutter.
- **Both Directions** (`B` while pulling): a symmetric pull, the same
  distance on both sides of the plane, like a CAD symmetric extrude.
- **Align Snap** (`A`, on by default): CAD-style tracking.
  - Hovered vertices are tracked (yellow dot).
  - The cursor snaps to the same height or side-to-side position as
    tracked vertices or drawn points, with cyan guide lines, and to the
    crossing of two lines.
  - While pulling a bool, hovering a vertex snaps the depth to its
    height.
- **Fix:** Boolean results are now visible in Edit Mode (Blender hides
  them by default), so cuts stay visible after Back to Mesh.
- Headless tests in Blender 5.2 all passed: Align Snap, symmetric pull,
  re-running from the panel (the cutter is reused, not duplicated),
  depth snapping, Apply and icons.
- README updated: Draw for Bool keys and options, the Snapping section
  and the controls table.

### 4. Both Directions toggle in the panel
- Symmetric cutting was only reachable with `B` while pulling or in the
  bottom-left panel, which made it hard to find. Added a **Both
  Directions** toggle under Auto / Cut / Extrude in the N panel, so it
  can be set before drawing. `B` keeps it in sync. Tests passed.

### 5. Pick step for Draw for Bool
- Pressing Auto / Cut / Extrude now starts with a **pick step**. The
  header asks you to click a face, or press Space (or click empty space)
  for the view plane through the 3D cursor. Nothing can be drawn until
  you pick.
- The face under the mouse is **highlighted** (cyan fill and outline)
  during the pick step.
- Headless tests passed: highlight on and off the mesh, keys blocked
  while picking, face pick, Space, and empty-space click.

### Open items
- Try the new features in the Blender UI: dragging, guide lines, and the
  bottom-left panel with redo after the mode switches.

---

## 2026-10-23 (Friday)

**Summary:** Fix Whole Chain and Extrude no longer need the vertices
clicked one by one. Then a code review for usability, and all 10
suggestions built: typed exact sizes, a shorter Average Vertex panel with
a live selection status, key help in the status bar, and tidier Bool
cutters. Version **3.5.0**.

### 1. Chain order without clicking one by one
- **Closed loops:** `Alt+click` a ring (or `A` on a circle) and Fix Whole
  Chain spaces it evenly around the full circle. Before, rings failed
  because the code looked for two open ends. Line and Curve refuse a loop
  with a clear message.
- **Loose vertices** (box select, no edges between them) are ordered by
  their shape: along the line, around the circle (starting after the
  biggest gap), or nearest neighbor for a curve.
- **Extrude** works on any selected path. The active vertex
  (`Shift+click`) picks the end to grow from. If there's no active end, it
  asks for one.
- Click order still wins when every vertex was clicked. Fix Last keeps
  using click order, because the last click is the target.
- The report says how the order was found (click order, edge path, edge
  loop or shape).
- Headless tests in Blender 5.2 passed: rings, edge paths, loose lines,
  arcs and U-shapes, extruding from the active end, and the error cases.

### 2. Usability review
Read through the whole add-on and listed 10 usability improvements. All
10 were built.

### 3. Usability round
- **Typed exact sizes:** after the first point, type a number for the
  length (Points), width / `Tab` / height (Rectangle) or radius (Circle),
  in the mouse's direction. While pulling a bool, type the exact depth
  (`-` flips it). Numbers use the scene's units.
- **Shorter Average Vertex panel:** one Line / Curve / Circle switch and
  a Keep Distance toggle drive the buttons: Fix Last Vertex, Fix Whole
  Chain (Fix Chain / Full Circle for circles), Extrude New Vertex and
  Move Last to Average. That's 6 buttons instead of 14.
- **Live selection status** in that panel: vertex count, how the order
  was found, and what's missing before you press anything.
- **Header and status bar:** the header now only shows what's going on.
  The key list moved to the status bar, so it no longer gets cut off.
- **Draw on Face** highlights the face under the mouse before the first
  click, like Draw for Bool's pick step.
- **Plane note** in the Draw panel only shows when it's true, and is more
  accurate.
- **Error messages** in Draw on Face point to Draw for Bool for shapes
  that go past the face's edge.
- **Shift+Q:** a Bool Cutters column (Edit Cutter, Back to Mesh, Apply
  Bool, Delete Cutter) shows up when there are cutters.
- **Delete Cutter:** throw a cutter away without applying it, from the
  panel (✕ per cutter) or Shift+Q.
- **Tidy cutters:** named Cut / Add / Intersect after what they do, and
  kept in a **VT Cutters** collection that's removed with the last
  cutter.
- Headless tests in Blender 5.2 passed: typed values for every shape and
  for the depth, mm scenes, naming, the collection, Delete Cutter, the
  status lines, and the panel and menu drawing code.
- README updated for all of it.

### 4. User Guide
- Wrote **USERGUIDE.md**, a step-by-step guide to every tool:
  - getting started
  - each Average Vertex button, with examples
  - Draw, typed sizes, planes and snapping
  - Draw on Face and Draw for Bool
  - Bool Cutters, Face Projection and the Shift+Q menu
  - recipes
  - troubleshooting for every error message
- Linked it from the README.

### Open items
- Try in the Blender UI: typing while drawing, the status bar text, the
  new Average Vertex panel, and the Shift+Q Bool Cutters column.
