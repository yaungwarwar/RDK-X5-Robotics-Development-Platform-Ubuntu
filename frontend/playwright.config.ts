import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  timeout: 45000,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.RDK_QA_BASE_URL || "http://127.0.0.1:8088",
    headless: true,
    launchOptions: { executablePath: process.env.RDK_TEST_BROWSER },
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1100 } } },
    {
      name: "mobile",
      use: {
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
