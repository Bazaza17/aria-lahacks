/** Normalized anchor in the centered mesh bounding box (0–1 per axis). */
export type NormalizedAnchor = {
  nx: number;
  ny: number;
  nz: number;
};

export type MeshSize = { x: number; y: number; z: number };

export function anchorToWorld(
  anchor: NormalizedAnchor,
  size: MeshSize,
): { x: number; y: number; z: number } {
  return {
    x: (anchor.nx - 0.5) * size.x,
    y: (anchor.ny - 0.5) * size.y,
    z: (anchor.nz - 0.5) * size.z,
  };
}

/** Floor-level waypoint — keeps routes on the ground plane of the scan. */
export function floorAnchor(nx: number, nz: number, floorNy: number): NormalizedAnchor {
  return { nx, ny: floorNy, nz };
}
