import { defineConfig } from "vitest/config";
export default defineConfig({
  build: { outDir: "../src/interview_copilot/web", emptyOutDir: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    restoreMocks: true,
  },
});
