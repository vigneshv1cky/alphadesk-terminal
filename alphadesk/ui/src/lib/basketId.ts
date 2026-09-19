/** A new basket's id (2026-09-18): "my-" and the name as a slug, with a
 * short random tail so two baskets with the same name never collide. The
 * server only accepts ids of this shape, so a reader's basket can never take
 * a curated basket's id. */
export function newBasketId(label: string, rand: () => number = Math.random): string {
  const slug = label.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 28)
  const tail = Math.floor(rand() * 36 ** 4).toString(36).padStart(4, "0")
  return `my-${slug ? `${slug}-` : ""}${tail}`
}
