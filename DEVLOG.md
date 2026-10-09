# Development Log — Vertex Tools

A day-by-day record of the work on the Vertex Tools Blender add-on
(`vertex_tools.py`), in the order it was done. Times are local (MDT).

---

## 2026-10-07 (Wednesday)

**Summary:** Merged two separate scripts into one add-on with its own
sidebar tab, put the project on Git, and grew it from 2 tools to 3
sections. Average Vertex got circle fitting and Preview & Apply. Draw With
Vertex got merging, shapes and snapping, plus Draw on Face. The new Face
Projection section aligns the view to a plane.
Version went to **3.3.0**. Commits: `35f634c` → `e4aa49b`.

### 1. Merging the two scripts (~4:20 PM)
- Compared `move_last_to_average.py` and `draw_with_vertex.py`.
- Merged them into one file, `vertex_tools.py`, with two separate
  sections, **Average Vertex** and **Draw with Vertex**, under
  **N Panel > Vertex Tools**.
- Wrote one combined README for both tools.

### 2. Git setup (~4:30 PM)
- Set up the Git repository and `.gitignore`, and made the first commit
  (`35f634c Vertex Tools`, 4:42 PM).
- Fixed getting stuck in the commit-message editor.

### 3. Merge option for Draw With Vertex (~4:47 PM)
- Added **Merge**: points snapped onto existing vertices are merged with
  them, so drawn faces really connect to the mesh.
- Installed the add-on into Blender 5.2 to replace the old version.
- **Bug fixed:** an `IndexError` in `_build_face` when merging into an
  existing vertex (stale vertex lookup table).

### 4. Edge snapping, Fix Whole Chain, Face Projection (~5:12 PM)
- **Edge snapping:** snap onto edges and their midpoints. With Merge on,
  the edge is split there.
- **Fix Whole Chain:** spaces an entire vertex chain evenly along a line
  or curve.
- **Face Projection** (new third section): align the view straight onto
  the plane of 3 vertices, 2 edges or 1 face.
- **Fix:** the aligned view's roll looked "weird". It's now chosen so the
  selection sits upright on screen.
- Commit `883827b Added new feature, Updated draw with vertex`
  (5:40 PM).

### 5. Feature round from the idea list (~5:58 PM)
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

### 6. Panel layout iterations (~6:26 PM)
- Explained the **Window** option in Preview & Apply.
- Made **Preview & Apply** a collapsible sub-panel.
- Tried a compact layout for the whole tab. It was **rejected** as too
  cramped and reverted. Kept: the collapsible Preview & Apply, and the
  compact snap icon row in Draw With Vertex.
- Restored the Window option, which had been removed by mistake.
- Audited the code against everything agreed so far. Everything was
  intact except the shortening idea, which was dropped on purpose.
- Commit `0816707 New Update` (6:43 PM).

### 7. Draw on Face (~6:48 PM)
- New **Draw on Face** button: click a face and draw a shape flat on its
  plane. Clicking empty space gives an error that points you to Draw.
- **Face Method** in the bottom-left panel:
  - **Cut In** (default)
  - **Replace (leave gap)**
  - **Auto-Bridge**
- Merging works against the face's own vertices and edges, so shapes can
  share edges with the outer face.

### 8. Auto-Bridge and visibility fixes (~7:08 PM)
- **Auto-Bridge rewritten:** it connects points to their *nearest*
  partners (no more faces stretching to far corners), joins triangles
  into quads, and checks that the result never overlaps.
- **Snap only to what you can see:** hidden vertices and edges are
  ignored unless X-ray is on.
- **Auto-Bridge options:** Attach Mode (Nearest / Even / Blender
  Bridge), a Twist slider and a Quad Angle slider. If the chosen setting
  would overlap, it automatically falls back to one that works.
- Explained **Flatten to Plane**.
- Commit `58abd1e Draw on Face Update` (7:31 PM).

### 9. README: Draw on Face vs. the Knife tool (~7:33 PM)
- Added a comparison table: where Draw on Face is better (exact shapes,
  flattening, grid, face methods, Auto-Bridge) and where the Knife is
  better (multi-face cuts, open cuts, Cut Through, freeform paths).
- Commit `e4aa49b Updated README.md` (7:37 PM). Version **3.3.0**.

---

## 2026-10-08 (Thursday)

**Summary:** Added a third draw mode, **Draw for Bool**: draw a shape,
pull it in or out by hand, and get a live, editable Boolean cutter or
adder object. Then added a symmetric (both directions) pull, a
bottom-left options panel and CAD-style **Align Snap**.
Version **3.4.0**. *(Not committed yet.)*

### 1. Review and design of Draw for Bool (~4:30 PM)
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

### 3. Both Directions, bottom-left panel, Align Snap (~5:07 PM)
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

### 4. Development log (~5:19 PM)
- Created this file, `DEVLOG.md`.

### 5. Both Directions toggle in the panel (~5:25 PM)
- Symmetric cutting was only reachable with `B` while pulling or in the
  bottom-left panel, which made it hard to find. Added a **Both
  Directions** toggle under Auto / Cut / Extrude in the N panel, so it
  can be set before drawing. `B` keeps it in sync. Tests passed.

### 6. Pick step for Draw for Bool (~5:35 PM)
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
- Commit today's work.
