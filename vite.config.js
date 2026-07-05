import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
  root: "frontend",
  plugins: [svelte()],
  build: {
    outDir: "../src/coordination_memory_mcp/static",
    emptyOutDir: true,
    minify: "esbuild",
    sourcemap: false,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "app.js",
        assetFileNames: (assetInfo) =>
          assetInfo.name && assetInfo.name.endsWith(".css") ? "styles.css" : "[name][extname]",
      },
    },
  },
  test: {
    environment: "node",
    include: ["test/**/*.test.js"],
  },
});
