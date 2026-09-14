export function placeAnnotations(entries, gap = 12) {
  const positions = {}
  let bottom = 0
  for (const entry of entries) {
    const top = Math.max(0, entry.anchorTop, bottom)
    positions[entry.key] = top
    bottom = top + entry.height + gap
  }
  return { positions, height: Math.max(120, bottom) }
}
