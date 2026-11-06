import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  use: { baseURL: "http://127.0.0.1:5183", channel: "chrome", headless: true },
  webServer: {
    command: "npm run dev -- --port 5183",
    url: "http://127.0.0.1:5183",
    reuseExistingServer: false,
  },
});
