export function placeAnnotations(entries, gap = 12, activeKey = null) {
  const ordered = [...entries].sort((a, b) => a.anchorTop - b.anchorTop)
  const positions = {}
  const activeIndex = ordered.findIndex(entry => entry.key === activeKey)
  let bottom = 0

  if (activeIndex >= 0) {
    // Keep the selected comment beside its text; use the space above for earlier comments.
    const active = ordered[activeIndex]
    const precedingHeight = ordered.slice(0, activeIndex).reduce((height, entry) => height + entry.height + gap, 0)
    positions[active.key] = Math.max(0, active.anchorTop, precedingHeight)
    let nextTop = positions[active.key]
    let requiredBefore = precedingHeight
    for (let i = activeIndex - 1; i >= 0; i--) {
      const entry = ordered[i]
      requiredBefore -= entry.height + gap
      const top = Math.max(requiredBefore, Math.min(Math.max(0, entry.anchorTop), nextTop - gap - entry.height))
      positions[entry.key] = top
      nextTop = top
    }
    bottom = positions[active.key] + active.height + gap
  }

  for (const entry of ordered.slice(activeIndex + 1)) {
    const top = Math.max(0, entry.anchorTop, bottom)
    positions[entry.key] = top
    bottom = top + entry.height + gap
  }
  return { positions, height: Math.max(120, bottom) }
}
