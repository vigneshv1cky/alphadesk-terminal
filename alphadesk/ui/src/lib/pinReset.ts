/** The one-time release of second and minute bars pinned on long ranges
 * (2026-10-05, the owner): they opened every month, quarter and year on tens of
 * thousands of bars. Short ranges keep their pins, and so does any bar of an
 * hour or more. A record marked `pinsReset: 1` is left exactly as it is, so a
 * minute bar picked on purpose afterwards stays. Pure. */
export const SHORT_RANGES: readonly string[] = ["1D", "5D"]

export function releaseLongMinutePins<K extends string>(
  byRange: Partial<Record<K, string>>,
  alreadyReset: boolean,
): Partial<Record<K, string>> {
  if (alreadyReset) return byRange
  const out: Partial<Record<K, string>> = {}
  for (const k of Object.keys(byRange) as K[]) {
    const iv = byRange[k] ?? ""
    if (!SHORT_RANGES.includes(k) && /^\d+(s|m)$/.test(iv)) continue
    out[k] = iv
  }
  return out
}
