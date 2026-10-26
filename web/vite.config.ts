import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // The LiveKit video library alone is about 0.8 MB, so we allow a bigger file
  // before Vite prints a size warning.
  build: { chunkSizeWarningLimit: 1500 },
});