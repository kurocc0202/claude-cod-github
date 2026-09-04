#!/usr/bin/env python3
"""Generate the 三井作造 character brush holder (筆筒) as a printable STL.

Four faces, one character each -- 三 front, 井 right, 作 back, 造 left. The
strokes are the wall and the load path, not decoration applied to a wall: each
runs into a corner post, and at every corner the two neighbouring faces share
the same 8 mm corner column, so they interlock rather than merely touch.

The body is described as overlapping axis-aligned boxes and then genuinely
unioned. Because every face is axis-aligned the union is exact: the box
coordinates are cut into a grid, cells are marked solid, and only the faces
between a solid and an empty cell are emitted. The result is watertight,
manifold, and free of self-intersections -- no boolean library, no loss of
precision, and nothing for a slicer to repair.

    python3 brush_holder.py                        # -> brush_holder.stl
    python3 brush_holder.py --preview holder.png
    python3 brush_holder.py --layer 0.16

Standard library only.
"""

import argparse
import bisect
import math
import struct
import sys
import zlib

# ---------------------------------------------------------------------------
# Body. Millimetres.
# ---------------------------------------------------------------------------

SIZE = 90.0            # outer width and depth
HEIGHT = 100.0
WALL = 8.0             # face depth; leaves a 74 mm square cavity
FLOOR = 4.0            # solid base, fully closed
RIM = 6.0              # continuous frame around the mouth
POST = 6.0             # square corner post, full height

DIVIDER = 5.0
DIVIDER_X = -7.0       # front-to-back divider, offset from centre
DIVIDER_Y = 5.0        # left-to-right divider, right half only

MIN_LAYERS = 2
MIN_MEMBER = 3.2       # spec floor for any structural member

GRID = 16
GLYPH_BOTTOM = FLOOR
GLYPH_TOP = HEIGHT - RIM

# Strokes as (u0, v0, u1, v1) in grid cells, origin bottom left of the face
# seen from outside. One cell is 5.625 mm both ways. The corner posts cover
# u 0.00-1.07 and 14.93-16.00, so a stroke reaching those is tied in.
GLYPHS = {
    "三": [
        (0.0, 11.4, 16.0, 13.0),
        (0.0, 7.0, 16.0, 8.6),      # was 1.2-14.8: it stopped 0.75 mm short of
                                    # the posts and hung as a 52 mm cantilever
        (0.0, 1.8, 16.0, 3.8),
    ],
    "井": [
        (0.0, 10.6, 16.0, 12.2),
        (0.0, 5.0, 16.0, 6.6),
        (4.2, 0.0, 5.8, 15.2),      # down to the floor: nothing starts mid air
        (9.6, 0.0, 11.2, 15.2),
    ],
    "作": [
        (1.6, 0.0, 3.2, 13.6),      # 亻 vertical, down to the floor
        (0.0, 11.0, 1.8, 13.6),     # 亻 head, into the left post
        (4.0, 12.4, 6.0, 14.6),     # 乍 top stroke
        (4.0, 11.0, 14.8, 12.6),    # 乍 first horizontal
        (8.0, 1.4, 9.6, 12.6),      # 乍 long vertical
        (5.6, 7.6, 14.0, 9.2),
        (5.6, 4.4, 14.0, 6.0),
        (5.6, 1.4, 16.0, 3.0),      # into the right post
    ],
    "造": [
        (0.0, 13.4, 2.2, 15.2),     # 辶 dot
        (0.0, 1.8, 1.8, 12.2),      # 辶 stem, continuous down into the sweep
        (0.0, 0.0, 16.0, 2.0),      # 辶 sweep, straight onto the floor
        (7.6, 12.8, 9.4, 16.0),     # 告 top stroke, up into the rim
        (5.4, 11.4, 13.8, 13.0),
        (8.6, 8.0, 10.4, 13.0),     # 告 vertical
        (4.4, 8.0, 16.0, 9.6),      # 告 long horizontal, into the right post
        (7.0, 5.4, 13.0, 7.0),      # 口, sitting on the 辶 sweep
        (7.0, 1.8, 8.6, 7.0),
        (11.4, 1.8, 13.0, 7.0),
        (7.0, 1.8, 13.0, 3.4),
    ],
}

# Outward axis of each face, and the direction the glyph reads in.
FACES = [
    ("三", "front", (0.0, -1.0), (1.0, 0.0)),
    ("井", "right", (1.0, 0.0), (0.0, 1.0)),
    ("作", "back", (0.0, 1.0), (-1.0, 0.0)),
    ("造", "left", (-1.0, 0.0), (0.0, -1.0)),
]

Q = 6                  # coordinates are rounded to this many decimals


def snap(value, layer):
    """Nearest layer boundary. Not round(), which is banker's rounding."""
    return math.floor(value / layer + 0.5) * layer


def cell_size():
    return SIZE / GRID, (GLYPH_TOP - GLYPH_BOTTOM) / GRID


# ---------------------------------------------------------------------------
# Solid: a list of boxes, unioned exactly
# ---------------------------------------------------------------------------

class Solid:
    def __init__(self, layer):
        self.layer = layer
        self.boxes = []

    def box(self, x0, y0, z0, x1, y1, z1):
        """Add a box. Heights snap to the layer grid; nothing thinner than one."""
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        z0, z1 = snap(min(z0, z1), self.layer), snap(max(z0, z1), self.layer)
        if z1 - z0 < MIN_LAYERS * self.layer - 1e-9:
            z1 = z0 + MIN_LAYERS * self.layer
        if x1 - x0 < 1e-6 or y1 - y0 < 1e-6:
            return
        self.boxes.append(tuple(round(v, Q) for v in (x0, y0, z0, x1, y1, z1)))

    def thinnest_member(self):
        return min(min(b[3] - b[0], b[4] - b[1], b[5] - b[2]) for b in self.boxes)

    # -- the union -------------------------------------------------------

    def _grid(self):
        xs = sorted({b[0] for b in self.boxes} | {b[3] for b in self.boxes})
        ys = sorted({b[1] for b in self.boxes} | {b[4] for b in self.boxes})
        zs = sorted({b[2] for b in self.boxes} | {b[5] for b in self.boxes})
        nx, ny, nz = len(xs) - 1, len(ys) - 1, len(zs) - 1
        solid = bytearray(nx * ny * nz)
        for x0, y0, z0, x1, y1, z1 in self.boxes:
            i0, i1 = bisect.bisect_left(xs, x0), bisect.bisect_left(xs, x1)
            j0, j1 = bisect.bisect_left(ys, y0), bisect.bisect_left(ys, y1)
            k0, k1 = bisect.bisect_left(zs, z0), bisect.bisect_left(zs, z1)
            for i in range(i0, i1):
                for j in range(j0, j1):
                    base = (i * ny + j) * nz
                    for k in range(k0, k1):
                        solid[base + k] = 1
        return xs, ys, zs, nx, ny, nz, solid

    def union(self):
        xs, ys, zs, nx, ny, nz, solid = self._grid()

        def at(i, j, k):
            if i < 0 or j < 0 or k < 0 or i >= nx or j >= ny or k >= nz:
                return 0
            return solid[(i * ny + j) * nz + k]

        verts = {}
        vlist = []

        def vert(i, j, k):
            key = (i, j, k)
            got = verts.get(key)
            if got is None:
                got = len(vlist)
                verts[key] = got
                vlist.append((xs[i], ys[j], zs[k]))
            return got

        tris = []

        def quad(a, b, c, d):
            tris.append((a, b, c))
            tris.append((a, c, d))

        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    if not solid[(i * ny + j) * nz + k]:
                        continue
                    if not at(i + 1, j, k):
                        quad(vert(i + 1, j, k), vert(i + 1, j + 1, k),
                             vert(i + 1, j + 1, k + 1), vert(i + 1, j, k + 1))
                    if not at(i - 1, j, k):
                        quad(vert(i, j, k), vert(i, j, k + 1),
                             vert(i, j + 1, k + 1), vert(i, j + 1, k))
                    if not at(i, j + 1, k):
                        quad(vert(i, j + 1, k), vert(i, j + 1, k + 1),
                             vert(i + 1, j + 1, k + 1), vert(i + 1, j + 1, k))
                    if not at(i, j - 1, k):
                        quad(vert(i, j, k), vert(i + 1, j, k),
                             vert(i + 1, j, k + 1), vert(i, j, k + 1))
                    if not at(i, j, k + 1):
                        quad(vert(i, j, k + 1), vert(i + 1, j, k + 1),
                             vert(i + 1, j + 1, k + 1), vert(i, j + 1, k + 1))
                    if not at(i, j, k - 1):
                        quad(vert(i, j, k), vert(i, j + 1, k),
                             vert(i + 1, j + 1, k), vert(i + 1, j, k))

        return Mesh(vlist, tris), (xs, ys, zs, nx, ny, nz, solid)


class Mesh:
    def __init__(self, vertices, triangles):
        self.vertices = vertices
        self.triangles = triangles

    def check_manifold(self):
        """Watertight and manifold: every directed edge used exactly once, and
        every edge carrying exactly one triangle in each direction."""
        seen = set()
        for a, b, c in self.triangles:
            for e in ((a, b), (b, c), (c, a)):
                if e in seen:
                    raise ValueError("edge %r used twice the same way: "
                                     "non-manifold" % (e,))
                seen.add(e)
        for a, b in seen:
            if (b, a) not in seen:
                raise ValueError("edge %r has no twin: not watertight" % ((a, b),))
        return len(seen) // 2

    def volume_mm3(self):
        total = 0.0
        for a, b, c in self.triangles:
            ax, ay, az = self.vertices[a]
            bx, by, bz = self.vertices[b]
            cx, cy, cz = self.vertices[c]
            total += (ax * (by * cz - bz * cy)
                      - ay * (bx * cz - bz * cx)
                      + az * (bx * cy - by * cx))
        return total / 6.0


# ---------------------------------------------------------------------------
# Checks on the voxel grid
# ---------------------------------------------------------------------------

def component_count(grid):
    """Solid cells joined face to face. Must be 1: one printable piece."""
    xs, ys, zs, nx, ny, nz, solid = grid
    seen = bytearray(len(solid))
    components = 0
    for start in range(len(solid)):
        if not solid[start] or seen[start]:
            continue
        components += 1
        stack = [start]
        seen[start] = 1
        while stack:
            n = stack.pop()
            k = n % nz
            j = (n // nz) % ny
            i = n // (nz * ny)
            for di, dj, dk in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                a, b, c = i + di, j + dj, k + dk
                if not (0 <= a < nx and 0 <= b < ny and 0 <= c < nz):
                    continue
                m = (a * ny + b) * nz + c
                if solid[m] and not seen[m]:
                    seen[m] = 1
                    stack.append(m)
    return components


def overhangs(grid):
    """How far unsupported material reaches from the nearest anchor, and the
    total downward-facing area that is not on the bed.

    Taking the bounding box of an unsupported patch is misleading: the
    underside of a horizontal stroke is a long thin rectangle, and the slicer
    does not bridge across its 8 mm width -- it bridges the ~78 mm between the
    corner posts holding its two ends. So this walks outwards, layer by layer,
    from the cells that do have material underneath them, and reports the
    furthest an unsupported cell sits from one. A bridge anchored at both ends
    spans about twice that; a cantilever reaches it.
    """
    xs, ys, zs, nx, ny, nz, solid = grid
    worst = 0.0
    area = 0.0
    islands = []

    def centre_x(i):
        return 0.5 * (xs[i] + xs[i + 1])

    def centre_y(j):
        return 0.5 * (ys[j] + ys[j + 1])

    for k in range(1, nz):
        supported = []
        loose = set()
        for i in range(nx):
            for j in range(ny):
                if not solid[(i * ny + j) * nz + k]:
                    continue
                if solid[(i * ny + j) * nz + k - 1]:
                    supported.append((i, j))
                else:
                    loose.add((i, j))
                    area += (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j])
        if not loose:
            continue

        dist = {cell: 0.0 for cell in supported}
        frontier = list(supported)
        while frontier:
            nxt = []
            for i, j in frontier:
                d = dist[(i, j)]
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    a, b = i + di, j + dj
                    if (a, b) not in loose:
                        continue
                    step = (abs(centre_x(a) - centre_x(i))
                            + abs(centre_y(b) - centre_y(j)))
                    nd = d + step
                    if nd < dist.get((a, b), 1e18) - 1e-9:
                        dist[(a, b)] = nd
                        nxt.append((a, b))
            frontier = nxt

        # Cells the walk never reached have no anchor anywhere in their layer:
        # they would start in mid air, held only by material above them.
        stranded = [c for c in loose if c not in dist]
        if stranded:
            members = set(stranded)
            while members:
                stack = [members.pop()]
                group = [stack[0]]
                while stack:
                    i, j = stack.pop()
                    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        n = (i + di, j + dj)
                        if n in members:
                            members.discard(n)
                            stack.append(n)
                            group.append(n)
                gx = [i for i, _ in group]
                gy = [j for _, j in group]
                islands.append((zs[k], xs[min(gx)], xs[max(gx) + 1],
                                ys[min(gy)], ys[max(gy) + 1]))
        for cell in loose:
            if cell in dist:
                worst = max(worst, dist[cell])

    return worst, area, islands


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def add_strokes(solid, char, outward, read):
    cu, cv = cell_size()
    half = 0.5 * SIZE
    ox, oy = outward
    rx, ry = read
    for u0, v0, u1, v1 in GLYPHS[char]:
        a0, a1 = u0 * cu - half, u1 * cu - half
        z0 = GLYPH_BOTTOM + v0 * cv
        z1 = GLYPH_BOTTOM + v1 * cv
        fx0, fy0 = ox * half + rx * a0, oy * half + ry * a0
        fx1, fy1 = ox * half + rx * a1, oy * half + ry * a1
        x0 = min(fx0, fx1) - (WALL if ox > 0 else 0.0)
        x1 = max(fx0, fx1) + (WALL if ox < 0 else 0.0)
        y0 = min(fy0, fy1) - (WALL if oy > 0 else 0.0)
        y1 = max(fy0, fy1) + (WALL if oy < 0 else 0.0)
        solid.box(x0, y0, z0, x1, y1, z1)


def build(layer):
    s = Solid(layer)
    half = 0.5 * SIZE
    inner = half - WALL

    s.box(-half, -half, 0.0, half, half, FLOOR)          # closed base

    for sx in (-1.0, 1.0):                               # corner posts
        for sy in (-1.0, 1.0):
            s.box(sx * half, sy * half, FLOOR,
                  sx * half - sx * POST, sy * half - sy * POST, HEIGHT)

    for char, _n, outward, read in FACES:
        add_strokes(s, char, outward, read)

    top = HEIGHT - RIM                                   # rim frame
    s.box(-half, -half, top, half, -half + RIM, HEIGHT)
    s.box(-half, half - RIM, top, half, half, HEIGHT)
    s.box(-half, -half, top, -half + RIM, half, HEIGHT)
    s.box(half - RIM, -half, top, half, half, HEIGHT)

    # Dividers, both wall to wall. Besides splitting the cavity they give the
    # middle of every face a support to stand on, which halves the span the
    # long horizontal strokes have to bridge. Both sit off centre, so the
    # compartments come out unequal rather than as four identical squares.
    s.box(DIVIDER_X - 0.5 * DIVIDER, -inner, FLOOR,
          DIVIDER_X + 0.5 * DIVIDER, inner, top)
    s.box(-inner, DIVIDER_Y - 0.5 * DIVIDER, FLOOR,
          inner, DIVIDER_Y + 0.5 * DIVIDER, top)

    return s


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_stl(mesh, path, name="mitsui_brush_holder"):
    with open(path, "wb") as fh:
        fh.write(name.encode("ascii", "replace")[:79].ljust(80, b"\0"))
        fh.write(struct.pack("<I", len(mesh.triangles)))
        for a, b, c in mesh.triangles:
            ax, ay, az = mesh.vertices[a]
            bx, by, bz = mesh.vertices[b]
            cx, cy, cz = mesh.vertices[c]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            n = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            fh.write(struct.pack("<12fH", nx / n, ny / n, nz / n,
                                 ax, ay, az, bx, by, bz, cx, cy, cz, 0))


def _png(path, width, height, rgb):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(rgb[y * stride:(y + 1) * stride])
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        fh.write(chunk(b"IEND", b""))


def _fill(buf, canvas_w, x0, y0, x1, y1, colour):
    for py in range(max(0, int(y0)), max(0, int(y1))):
        row = py * canvas_w
        for px in range(max(0, int(x0)), max(0, int(x1))):
            o = (row + px) * 3
            buf[o], buf[o + 1], buf[o + 2] = colour


def _face_map(char, buf, canvas_w, ox, oy, tile):
    """Flat elevation of one face. A straight-on 3D view of a hollow box shows
    the far wall through the gaps, which hides the character."""
    pad = 0.10 * tile
    span = tile - 2 * pad
    cu, cv = cell_size()
    post_cells = POST / cu
    floor_cells = FLOOR / cv
    rim_cells = RIM / cv
    total_v = floor_cells + GRID + rim_cells
    sx, sy = span / GRID, span / total_v

    def rect(u0, v0, u1, v1, colour):
        _fill(buf, canvas_w, ox + pad + u0 * sx,
              oy + pad + (total_v - floor_cells - v1) * sy,
              ox + pad + u1 * sx,
              oy + pad + (total_v - floor_cells - v0) * sy, colour)

    frame, ink = (206, 206, 210), (34, 34, 36)
    rect(0.0, -floor_cells, GRID, 0.0, ink)
    rect(0.0, GRID, GRID, GRID + rim_cells, ink)
    rect(0.0, 0.0, post_cells, GRID, frame)
    rect(GRID - post_cells, 0.0, GRID, GRID, frame)
    for u0, v0, u1, v1 in GLYPHS[char]:
        rect(u0, v0, u1, v1, ink)


def _render_view(mesh, width, height, azimuth, elevation, buf, ox, oy, canvas_w):
    ca, sa = math.cos(math.radians(azimuth)), math.sin(math.radians(azimuth))
    ce, se = math.cos(math.radians(elevation)), math.sin(math.radians(elevation))

    def view(p):
        x, y, z = p
        x, y = x * ca + y * sa, -x * sa + y * ca
        return x, z * ce - y * se, -(y * ce + z * se)

    pts = [view(v) for v in mesh.vertices]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    scale = 0.86 * min(width, height) / span
    cx, cy = 0.5 * (max(xs) + min(xs)), 0.5 * (max(ys) + min(ys))
    screen = [((p[0] - cx) * scale + width * 0.5,
               height * 0.5 - (p[1] - cy) * scale, p[2]) for p in pts]

    depth = [-1e18] * (width * height)
    light = (-0.40, 0.48, 0.78)

    for a, b, c in mesh.triangles:
        x0, y0, z0 = screen[a]
        x1, y1, z1 = screen[b]
        x2, y2, z2 = screen[c]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if area >= -1e-9:
            continue
        ax, ay, az = mesh.vertices[a]
        bx, by, bz = mesh.vertices[b]
        ccx, ccy, ccz = mesh.vertices[c]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = ccx - ax, ccy - ay, ccz - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        lam = max(0.0, (nx * light[0] + ny * light[1] + nz * light[2]) / nl)
        base = 214.0 * (0.26 + 0.74 * lam ** 0.8)
        colour = (int(min(255.0, base)), int(min(255.0, base)),
                  int(min(255.0, base + 3.0)))

        lo_x, hi_x = max(0, int(min(x0, x1, x2))), min(width - 1, int(max(x0, x1, x2)) + 1)
        lo_y, hi_y = max(0, int(min(y0, y1, y2))), min(height - 1, int(max(y0, y1, y2)) + 1)
        if lo_x > hi_x or lo_y > hi_y:
            continue
        inv = 1.0 / area
        for py in range(lo_y, hi_y + 1):
            sy = py + 0.5
            for px in range(lo_x, hi_x + 1):
                sx = px + 0.5
                w0 = ((x1 - sx) * (y2 - sy) - (x2 - sx) * (y1 - sy)) * inv
                if w0 < 0.0:
                    continue
                w1 = ((x2 - sx) * (y0 - sy) - (x0 - sx) * (y2 - sy)) * inv
                if w1 < 0.0:
                    continue
                w2 = 1.0 - w0 - w1
                if w2 < 0.0:
                    continue
                zz = w0 * z0 + w1 * z1 + w2 * z2
                idx = py * width + px
                if zz <= depth[idx]:
                    continue
                depth[idx] = zz
                o = ((oy + py) * canvas_w + ox + px) * 3
                buf[o], buf[o + 1], buf[o + 2] = colour


def render_preview(mesh, path, tile=440):
    width, height = tile * 4, tile * 2
    bg = (245, 245, 247)
    buf = bytearray(bg[i % 3] for i in range(width * height * 3))
    for i, (char, _n, _o, _r) in enumerate(FACES):
        _face_map(char, buf, width, i * tile, 0, tile)
    _render_view(mesh, tile * 2, tile, 34.0, 24.0, buf, tile, tile, width)
    _png(path, width, height, buf)


# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--layer", type=float, default=0.2)
    p.add_argument("--nozzle", type=float, default=0.4)
    p.add_argument("--preview", metavar="PNG")
    p.add_argument("-o", "--out", default="brush_holder.stl")
    args = p.parse_args(argv)

    if args.layer <= 0.0:
        print("error: layer height must be positive", file=sys.stderr)
        return 2

    solid = build(args.layer)
    mesh, grid = solid.union()
    edges = mesh.check_manifold()
    parts = component_count(grid)
    span, area, islands = overhangs(grid)
    thin = solid.thinnest_member()
    volume = mesh.volume_mm3()
    write_stl(mesh, args.out)

    cu, cv = cell_size()
    print("%s  %.0f x %.0f x %.0f mm" % (args.out, SIZE, SIZE, HEIGHT))
    print("  faces: " + ", ".join("%s %s" % (n, c) for c, n, _o, _r in FACES))
    print("  cavity %.0f x %.0f mm, %.0f mm deep, base closed at %.1f mm"
          % (SIZE - 2 * WALL, SIZE - 2 * WALL, HEIGHT - FLOOR - 0.0, FLOOR))
    print()
    print("  mesh    %d boxes unioned -> %d triangles, %d edges"
          % (len(solid.boxes), len(mesh.triangles), edges))
    print("          watertight, manifold, no self-intersections")
    print("  solid   %d connected component%s%s"
          % (parts, "" if parts == 1 else "s",
             "" if parts == 1 else "   FLOATING GEOMETRY"))
    print("  layer   %.2f mm; glyph cell %.3f x %.3f mm (%d layers)"
          % (args.layer, cu, cv, int(round(cv / args.layer))))
    print("  member  thinnest %.2f mm%s  (spec >= %.1f, %.0f nozzle widths)"
          % (thin, "" if thin >= MIN_MEMBER - 1e-9 else "   UNDER SPEC",
             MIN_MEMBER, thin / args.nozzle))
    print("  bridge  unsupported material reaches %.1f mm from an anchor"
          % span)
    print("          (a stroke held at both ends spans about %.0f mm), "
          "%.1f cm2 facing down" % (2.0 * span, area / 100.0))
    if islands:
        print("  MID-AIR STARTS: %d place%s where a layer has no anchor at all"
              % (len(islands), "" if len(islands) == 1 else "s"))
        for z, x0, x1, y0, y1 in islands:
            print("    z %6.2f mm   x %7.2f..%-7.2f  y %7.2f..%-7.2f"
                  % (z, x0, x1, y0, y1))
    else:
        print("  support every layer rests on the one below it")
    print("  volume  %.1f cm3 solid (~%.0f g PLA at 1.24 g/cm3, before infill)"
          % (volume / 1000.0, volume / 1000.0 * 1.24))

    if args.preview:
        render_preview(mesh, args.preview)
        print("  preview %s" % args.preview)

    return 0


if __name__ == "__main__":
    sys.exit(main())
