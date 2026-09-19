import fs from "fs"
import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, type Plugin } from "vite"

const LICENSE_FILES = ["LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "license", "license.md", "OFL.txt"]

/** Writes third-party-notices.txt beside the bundle: every package whose
 * code, styles or fonts the BUILD actually pulled in, with its licence text.
 * MIT, ISC and the fonts' SIL Open Font License all require their notice to
 * travel with copies, and the minified bundle keeps none (2026-09-19). Read
 * from the build's own module graph, so the list cannot drift from what
 * ships — build-only packages (Vite, Tailwind's compiler) never appear. */
function thirdPartyNotices(): Plugin {
  return {
    name: "third-party-notices",
    apply: "build",
    generateBundle() {
      const dirs = new Map<string, string>()
      for (const id of this.getModuleIds()) {
        const clean = id.replace(/^\0/, "").split("?")[0]
        const at = clean.lastIndexOf("/node_modules/")
        if (at < 0) continue
        const rest = clean.slice(at + "/node_modules/".length).split("/")
        const name = rest[0].startsWith("@") ? `${rest[0]}/${rest[1]}` : rest[0]
        dirs.set(name, clean.slice(0, at + "/node_modules/".length) + name)
      }
      // Tailwind inlines a stylesheet's @import and url() targets itself, so
      // the fonts and Tailwind's base styles never reach the module graph:
      // they are read from the app's own stylesheets instead.
      for (const id of this.getModuleIds()) {
        const clean = id.replace(/^\0/, "").split("?")[0]
        if (!clean.endsWith(".css") || clean.includes("/node_modules/") || !fs.existsSync(clean)) continue
        const css = fs.readFileSync(clean, "utf8")
        for (const m of css.matchAll(/@import\s+["']([^"'.\/][^"']*)["']|url\(["']?[^)"']*node_modules\/([^)"']+)/g)) {
          const spec = (m[1] ?? m[2]).split("/")
          const name = spec[0].startsWith("@") ? `${spec[0]}/${spec[1]}` : spec[0]
          const dir = path.resolve(__dirname, "node_modules", name)
          if (fs.existsSync(path.join(dir, "package.json"))) dirs.set(name, fs.realpathSync(dir))
        }
      }
      const blocks = [...dirs.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([name, dir]) => {
        const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"))
        const file = LICENSE_FILES.map(f => path.join(dir, f)).find(f => fs.existsSync(f))
        const text = file ? fs.readFileSync(file, "utf8").trim() : `Licence: ${pkg.license ?? "see the package"}`
        return `${"=".repeat(80)}\n${name} ${pkg.version} — ${pkg.license ?? "unknown"}\n${"=".repeat(80)}\n\n${text}\n`
      })
      this.emitFile({
        type: "asset", fileName: "third-party-notices.txt",
        source: "AlphaDesk's web interface includes the following third-party software and fonts.\n"
          + "AlphaDesk itself is licensed separately; see LICENSE in its repository.\n\n" + blocks.join("\n"),
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), thirdPartyNotices()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    // built bundle is served by FastAPI (alphadesk/app/dashboard.py)
    outDir: path.resolve(__dirname, "../app/static"),
    emptyOutDir: true,
  },
  server: {
    // local dev: proxy API to the running engine
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
})
