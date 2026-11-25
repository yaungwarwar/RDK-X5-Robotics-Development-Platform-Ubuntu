import { test, expect } from "@playwright/test";

test("all pages, responsive layout and mock identification", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByText("MOCK DATA", { exact: true })).toBeVisible();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "CPU utilization history" }),
  ).toBeVisible();
  await expect
    .poll(
      async () =>
        await page
          .getByRole("img", { name: "CPU utilization history" })
          .locator("path")
          .getAttribute("d"),
    )
    .toMatch(/L.*L.*L.*L/);
  await page.screenshot({
    path: `../docs/screenshots/mock-overview-${info.project.name}.png`,
    fullPage: true,
  });
  for (const name of [
    "Hardware",
    "Cameras",
    "BPU",
    "ROS2",
    "Network",
    "Containers",
    "Diagnostics",
    "About",
    "Overview",
  ]) {
    if (info.project.name === "mobile")
      await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page.getByRole("button", { name, exact: true }).click();
    await expect(
      page.getByRole("heading", { name, exact: true, level: 1 }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  if (info.project.name === "desktop") {
    await page.getByRole("button", { name: "Collapse sidebar" }).click();
    await expect(
      page.getByRole("button", { name: "Expand sidebar" }),
    ).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test("disconnect, stale data and automatic reconnection", async ({ page }) => {
  let drop = false;
  await page.routeWebSocket("**/ws/v1/telemetry", (ws) => {
    if (drop) {
      ws.close();
      return;
    }
    const server = ws.connectToServer();
    server.onMessage((message) => {
      if (!drop) ws.send(message);
      else {
        server.close();
        ws.close();
      }
    });
  });
  await page.goto("/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  drop = true;
  await expect(page.getByRole("alert")).toBeVisible({ timeout: 10000 });
  await expect(page.getByRole("alert")).toContainText("STALE DATA", {
    timeout: 12000,
  });
  drop = false;
  await expect(page.getByText("Connected", { exact: true })).toBeVisible({
    timeout: 20000,
  });
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("unavailable measurements and failed services remain explicit", async ({
  page,
}) => {
  await page.routeWebSocket("**/ws/v1/telemetry", (ws) => {
    const server = ws.connectToServer();
    server.onMessage((message) => {
      const data = JSON.parse(String(message));
      data.data.thermal.cpu.value = null;
      data.data.thermal.cpu.status = "unavailable";
      data.data.thermal.cpu.reason = "Thermal zone permission denied";
      data.data.services.docker.value.active = "failed";
      ws.send(JSON.stringify(data));
    });
  });
  await page.goto("/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Unavailable", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("failed", { exact: true })).toHaveClass(/bad/);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("BPU zero, dedicated sensor absence and retained ROS2 failure are explicit", async ({
  page,
}, info) => {
  await page.routeWebSocket("**/ws/v1/telemetry", (ws) => {
    const server = ws.connectToServer();
    server.onMessage((message) => {
      const data = JSON.parse(String(message));
      data.data.bpu.utilization.value = 0;
      data.data.bpu.cpu_temperature_proxy.value = 58.728;
      data.data.ros2.available.value = null;
      data.data.ros2.available.reason = "ROS2 probe timed out after 8 seconds";
      data.data.ros2.detail.value = "ROS2 probe timed out after 8 seconds";
      data.data.ros2.diagnostic.value = "timeout";
      data.data.ros2.probe_duration.value = 8.002;
      data.data.ros2.consecutive_failures.value = 2;
      data.data.ros2.nodes.stale = true;
      data.data.ros2.topics.stale = true;
      ws.send(JSON.stringify(data));
    });
  });
  await page.goto("/");
  await expect(
    page.getByRole("meter", { name: "BPU utilization" }),
  ).toHaveAttribute("aria-valuenow", "0");
  const navigate = async (name: string) => {
    if (info.project.name === "mobile")
      await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page.getByRole("button", { name, exact: true }).click();
  };
  await navigate("BPU");
  await expect(
    page.getByText(
      "CPU proxy is not an independently measured BPU temperature.",
    ),
  ).toBeVisible();
  await expect(page.getByText("58.7", { exact: true }).first()).toBeVisible();
  await page.screenshot({
    path: `../docs/screenshots/mock-bpu-${info.project.name}.png`,
    fullPage: true,
  });
  await navigate("ROS2");
  await expect(
    page
      .getByText("ROS2 probe timed out after 8 seconds", { exact: true })
      .first(),
  ).toBeVisible();
  await expect(page.getByText("Consecutive discovery failures")).toBeVisible();
  await expect(page.getByText("/mipi_cam", { exact: true })).toBeVisible();
  await page.screenshot({
    path: `../docs/screenshots/mock-ros2-${info.project.name}.png`,
    fullPage: true,
  });
});

test("CPU chart preserves unavailable gaps and isolated valid samples", async ({
  page,
}) => {
  let index = 0;
  await page.routeWebSocket("**/ws/v1/telemetry", (ws) => {
    const server = ws.connectToServer();
    server.onMessage((message) => {
      const data = JSON.parse(String(message));
      data.sequence = ++index;
      data.data.cpu.overall.value = index === 2 ? null : 30 + index;
      data.data.cpu.overall.reason =
        index === 2 ? "No positive CPU-time delta" : null;
      ws.send(JSON.stringify(data));
    });
  });
  await page.goto("/");
  const chart = page.getByRole("img", { name: "CPU utilization history" });
  await expect
    .poll(async () => await chart.locator("path").getAttribute("d"))
    .toMatch(/M.*M/);
  await expect(chart.locator("circle").first()).toBeVisible();
  await expect(
    page.getByText(/1 unavailable\/stale samples in this window/),
  ).toBeVisible();
});

test("existing browser tab tolerates the older API after rollback", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.routeWebSocket("**/ws/v1/telemetry", (ws) => {
    const server = ws.connectToServer();
    server.onMessage((message) => {
      const data = JSON.parse(String(message));
      data.version = "0.1.0";
      for (const field of [
        "probe_duration",
        "last_success",
        "consecutive_failures",
        "diagnostic",
        "detail",
        "stderr_excerpt",
      ])
        delete data.data.ros2[field];
      delete data.data.bpu.cpu_temperature_proxy;
      delete data.data.bpu.temperature_fallback;
      ws.send(JSON.stringify(data));
    });
  });
  await page.goto("/");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  for (const name of ["BPU", "ROS2", "Cameras", "Overview"]) {
    if (info.project.name === "mobile")
      await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page.getByRole("button", { name, exact: true }).click();
    await expect(
      page.getByRole("heading", { name, exact: true, level: 1 }),
    ).toBeVisible();
  }
  expect(errors).toEqual([]);
});
