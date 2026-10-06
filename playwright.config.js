const { defineConfig, devices } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: { baseURL: "http://127.0.0.1:5056", trace: "retain-on-failure" },
  projects: [
    {
      name: "iphone-chromium",
      use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" },
    },
    {
      name: "iphone-webkit",
      use: {
        ...devices["iPhone 13"],
        defaultBrowserType: "webkit",
        serviceWorkers: "block",
      },
    },
    {
      name: "desktop",
      use: { browserName: "chromium", viewport: { width: 1440, height: 1000 } },
    },
  ],
  webServer: {
    command:
      process.env.MYHUB_TEST_SERVER ||
      (process.platform === "win32"
        ? ".venv\\Scripts\\python.exe -m flask --app app run --port 5056"
        : "python -m flask --app app run --port 5056"),
    url: "http://127.0.0.1:5056/health",
    reuseExistingServer: !process.env.CI,
  },
});
