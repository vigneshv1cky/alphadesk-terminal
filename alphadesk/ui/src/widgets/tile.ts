/** The tile height CAP.
 *
 * Tiles size to their content and stop growing here (2026-09-02, "make short
 * tiles shrink to their content"). A long list scrolls inside the cap; a
 * three-row stat grid is a three-row tile. The uniform-440px rule this file
 * used to declare was reversed once the opt-in widget wave added tiles whose
 * content is a fraction of a row — uniformity left them two-thirds blank.
 *
 * The widget header costs 38px, so the body's cap is the remainder.
 */
export const TILE_HEIGHT = 440
export const TILE_BODY_HEIGHT = TILE_HEIGHT - 38
