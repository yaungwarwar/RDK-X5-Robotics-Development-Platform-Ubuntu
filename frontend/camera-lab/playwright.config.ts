import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  timeout: 20000,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:18100",
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
  webServer:
    process.env.RDK_LAB_EXTERNAL === "1"
      ? undefined
      : {
          command:
            '"${RDK_TEST_PYTHON:-.venv-recovered/bin/python}" prototype/camera_lab/server.py',
          cwd: fileURLToPath(new URL("../..", import.meta.url)),
          url: "http://127.0.0.1:18100/lab/status",
          reuseExistingServer: false,
          timeout: 15000,
        },
});
