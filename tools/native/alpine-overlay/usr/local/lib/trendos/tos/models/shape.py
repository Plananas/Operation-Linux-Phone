"""Shape (what the renderer draws) and the building blocks for making new ones.

A Shape is a cloud of surface points grouped into flat faces; each face has one outward normal
(for back-face culling and lighting) and one palette colour. Points just need to be dense enough
that every character cell a face covers gets at least one (about 17 per unit is right at
launcher size); the z-buffer hides whatever ends up behind.

Building blocks:
  boxes(...)     union of axis-aligned boxes (plus sign, bars, ...)
  extrude(...)   any 2D silhouette pushed into a slab, with shaded side walls (coins, logos, ...)
  arc(...)       points along a circular arc, for building extrude outlines
"""
import math

import numpy as np

DENSITY = 17                    # sample points per unit length
SEG = 0.09                      # side-wall facet length: short enough that curves shade smoothly


class Shape:
    """pts (N,3), fid (N,) face of each point (non-decreasing), fnrm (F,3) outward normals,
    fcol (F,) palette index per face."""

    def __init__(self, pts, fid, fnrm, fcol):
        self.pts = np.ascontiguousarray(pts, np.float32)
        self.fid = np.ascontiguousarray(fid, np.int32)
        self.fnrm = np.ascontiguousarray(fnrm, np.float32)
        self.fcol = np.ascontiguousarray(fcol, np.int32)
        self.fstart = np.ascontiguousarray(np.searchsorted(self.fid, np.arange(len(self.fnrm) + 1)), np.int32)
        self.face_idx = [np.arange(self.fstart[i], self.fstart[i + 1]) for i in range(len(self.fnrm))]
        self.fcen = np.ascontiguousarray([self.pts[ix].mean(0) for ix in self.face_idx], np.float32)
        self.cptr = tuple(a.ctypes.data for a in (self.pts, self.fid, self.fstart)) + (len(self.fnrm),) + \
                    tuple(a.ctypes.data for a in (self.fnrm, self.fcen, self.fcol))

    @classmethod
    def from_faces(cls, faces):
        """faces: [(points (k,3), normal (3,), palette index)], each with at least one point."""
        pts = np.concatenate([np.asarray(p, np.float32).reshape(-1, 3) for p, _, _ in faces])
        fid = np.concatenate([np.full(len(p), i, np.int32) for i, (p, _, _) in enumerate(faces)])
        return cls(pts, fid, [np.asarray(n, np.float32) for _, n, _ in faces], [c for _, _, c in faces])


def boxes(spec, colour_by_axis, density=DENSITY):
    """Union of axis-aligned boxes [(centre, half_sizes)] (the z-buffer hides the inner parts).
    colour_by_axis = palette index for faces normal to (x, y, z)."""
    faces = []
    for centre, half in spec:
        c, h = np.asarray(centre, np.float32), np.asarray(half, np.float32)
        for axis in range(3):
            u, v = (axis + 1) % 3, (axis + 2) % 3
            nu, nv = max(2, int(2 * h[u] * density)), max(2, int(2 * h[v] * density))
            gu, gv = np.meshgrid(((np.arange(nu) + 0.5) / nu * 2 - 1) * h[u],
                                 ((np.arange(nv) + 0.5) / nv * 2 - 1) * h[v])
            for sign in (-1, 1):
                p = np.zeros((nu * nv, 3), np.float32)
                p[:, axis] = sign * h[axis]; p[:, u] = gu.ravel(); p[:, v] = gv.ravel()
                n = np.zeros(3, np.float32); n[axis] = sign
                faces.append((p + c, n, colour_by_axis[axis]))
    return Shape.from_faces(faces)


def arc(cx, cy, r, a0, a1, seg=SEG):
    """Points along a circular arc from angle a0 to a1 (radians; a1 < a0 goes clockwise)."""
    k = max(2, int(abs(a1 - a0) * r / seg) + 1)
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / k), cy + r * math.sin(a0 + (a1 - a0) * i / k))
            for i in range(k + 1)]


def extrude(inside, outlines, depth, colour, extent=1.0, density=DENSITY):
    """A 2D silhouette pushed into a slab of half-thickness `depth` (front face towards the
    camera at -z).

    inside(x, y) -> bool   whether a point is part of the silhouette; the front and back faces
                           are sampled on a grid over [-extent, extent]^2 with it.
    outlines               polylines [(x, y), ...] along the silhouette's edges, which become the
                           side walls: trace outer edges counter-clockwise and holes clockwise
                           (solid on the left of the direction of travel), so each wall facet's
                           normal points out of the solid. Leave an edge out for no wall there.
    colour                 palette index, or (front/back, walls).
    """
    face_col, wall_col = colour if isinstance(colour, tuple) else (colour, colour)
    n = max(2, int(2 * extent * density))
    g = ((np.arange(n) + 0.5) / n * 2 - 1) * extent
    flat = [(x, y) for y in g for x in g if inside(x, y)]
    faces = [([(x, y, z) for x, y in flat], (0, 0, -1 if z < 0 else 1), face_col) for z in (-depth, depth)]

    nz = max(2, int(2 * depth * density))
    zs = ((np.arange(nz) + 0.5) / nz * 2 - 1) * depth
    for path in outlines:
        for (x0, y0), (x1, y1) in zip(path, path[1:]):
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if length < 1e-6:
                continue
            k = max(1, int(length * density))
            pts = [(x0 + dx * (i + 0.5) / k, y0 + dy * (i + 0.5) / k, z) for i in range(k) for z in zs]
            faces.append((pts, (dy / length, -dx / length, 0), wall_col))   # right of travel = out
    return Shape.from_faces(faces)
