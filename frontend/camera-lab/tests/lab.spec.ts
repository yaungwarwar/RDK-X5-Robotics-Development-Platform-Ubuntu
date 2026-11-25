import { test, expect } from "@playwright/test";

test("synthetic stream starts, switches, stops and cleans up", async ({
  page,
  request,
}, testInfo) => {
  await page.goto("/");
  await expect(page.locator(".mock")).toBeVisible();
  await expect(page.getByText("Preview is inactive")).toBeVisible();
  await page.getByRole("button", { name: "Start preview" }).click();
  await expect(
    page.getByAltText("Synthetic left camera preview"),
  ).toBeVisible();
  await expect
    .poll(() =>
      page
        .getByAltText("Synthetic left camera preview")
        .evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBe(640);
  await expect(page.getByText("Synthetic source active")).toBeVisible();
  await expect(page.getByText("640 × 360")).toBeVisible();
  await expect(
    page
      .locator("dl div")
      .filter({ hasText: "Broker process peak RSS" })
      .locator("dd"),
  ).not.toHaveText("Unavailable");
  await expect(
    page
      .locator("dl div")
      .filter({ hasText: "Broker process CPU" })
      .locator("dd"),
  ).not.toHaveText("Unavailable");
  await page.screenshot({
    path: `docs/screenshots/camera-lab-${testInfo.project.name}.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "Right camera" }).click();
  await expect(
    page.getByAltText("Synthetic right camera preview"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Combined stereo" }).click();
  await expect(
    page.getByAltText("Synthetic combined camera preview"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Stop preview" }).click();
  await expect(page.getByText("Preview is inactive")).toBeVisible();
  await expect
    .poll(
      async () =>
        (await (await request.get("/lab/status")).json()).active_clients,
    )
    .toBe(0);
});

test("disconnect cleans up and reconnect starts a fresh session", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Start preview" }).click();
  await expect(
    page.getByAltText("Synthetic left camera preview"),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByText("Preview is inactive")).toBeVisible();
  await expect
    .poll(
      async () =>
        (await (await request.get("/lab/status")).json()).active_clients,
    )
    .toBe(0);
  await page.getByRole("button", { name: "Start preview" }).click();
  await expect(
    page.getByAltText("Synthetic left camera preview"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Stop preview" }).click();
});

test("publisher disappearance marks the last frame stale", async ({ page }) => {
  await page.routeWebSocket("**/lab/preview/**", (socket) => {
    socket.send(
      JSON.stringify({
        type: "frame",
        sequence: 1,
        view: "left",
        source: "synthetic",
        encoding: "image/svg+xml",
        width: 640,
        height: 360,
        fps: null,
        bandwidth_bps: null,
        dropped: 0,
        frame_age_ms: 0,
        calibration: null,
      }),
    );
    socket.send(
      Buffer.from(
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"></svg>',
      ),
    );
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Start preview" }).click();
  await expect(
    page.getByAltText("Synthetic left camera preview"),
  ).toBeVisible();
  await expect(page.getByText("Stale frame")).toBeVisible({ timeout: 5000 });
  await page.getByRole("button", { name: "Stop preview" }).click();
});

test("native selection displays received calibration and stops", async ({
  page,
}) => {
  await page.routeWebSocket("**/lab/preview/**", (socket) => {
    socket.send(
      JSON.stringify({ type: "error", message: "Invalid fixture message" }),
    );
    socket.onMessage(() =>
      socket.send(
        JSON.stringify({
          type: "status",
          publishers: 0,
          message: "No publisher detected",
        }),
      ),
    );
    socket.send(
      JSON.stringify({
        type: "frame",
        sequence: 1,
        view: "left",
        source: "native",
        mime: "image/png",
        encoding: "nv12",
        display_mode: "grayscale luminance (NV12)",
        width: 1,
        height: 1,
        fps: null,
        bandwidth_bps: null,
        dropped: 0,
        frame_age_ms: 0,
        calibration: {
          "/image_left_raw/camera_info": {
            width: 1,
            height: 1,
            model: "plumb_bob",
            k: [1, 0, 0, 0, 1, 0, 0, 0, 1],
            d: [0.1],
            intrinsics_present: true,
          },
        },
      }),
    );
    socket.send(
      Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aWQAAAAASUVORK5CYII=",
        "base64",
      ),
    );
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Native ROS2" }).click();
  await expect(page.locator(".mock")).toBeVisible();
  await page.getByRole("button", { name: "Start preview" }).click();
  await expect(page.getByAltText("Native left camera preview")).toBeVisible();
  await expect(
    page.getByText(
      /intrinsics present.*not independently validated.*plumb_bob/,
    ),
  ).toBeVisible();
  await expect(page.getByText("grayscale luminance (NV12)")).toBeVisible();
  await expect(page.getByText("Invalid fixture message")).toBeVisible();
  await expect(page.getByText("No publisher detected").first()).toBeVisible();
  await page.getByRole("button", { name: "Stop preview" }).click();
});

test("metric labels state their measurement boundaries", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByText("Broker sent FPS (session average)"),
  ).toBeVisible();
  await expect(
    page.getByText("Age since broker receipt (lower bound)"),
  ).toBeVisible();
  await expect(
    page.getByText("Sent image payload (session average)"),
  ).toBeVisible();
  await expect(page.getByText("Broker process peak RSS")).toBeVisible();
  await expect(page.getByText("Browser acknowledged frames")).toBeVisible();
});

for (const [publishers, expected] of [
  [0, "No publisher detected"],
  [1, "Publisher present (1); no fresh usable frame"],
] as const) {
  test(`publisher count ${publishers} remains distinct from usable frames`, async ({
    page,
  }) => {
    await page.routeWebSocket("**/lab/preview/**", (socket) => {
      socket.send(
        JSON.stringify({
          type: "status",
          publishers,
          message: "Publisher update",
        }),
      );
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Native ROS2" }).click();
    await page.getByRole("button", { name: "Start preview" }).click();
    await expect(page.getByText(expected)).toBeVisible();
  });
}

test("native failure is explicit and never falls back to synthetic", async ({
  page,
}) => {
  await page.routeWebSocket("**/lab/preview/**", (socket) => {
    socket.send(
      JSON.stringify({ type: "error", message: "Native worker unavailable" }),
    );
    socket.close();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Native ROS2" }).click();
  await page.getByRole("button", { name: "Start preview" }).click();
  await expect(
    page.getByText(/Native worker unavailable/).first(),
  ).toBeVisible();
  await expect(page.getByAltText(/Synthetic/)).toHaveCount(0);
});
