// One owned QA session: backend tests, native proxy, production UI and browser checks.
import { spawnSync } from "node:child_process";
import { assertPortsFree, startOwned, waitForServices, runGuarded, stopOwned } from "./qa_process_guard.mjs";
import { mkdtempSync, readFileSync, writeFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const option = (name) => {
  const i = process.argv.indexOf(name);
  return i < 0 ? undefined : process.argv[i + 1];
};
const python =
  option("--python") ||
  process.env.RDK_TEST_PYTHON ||
  join(root, ".venv/bin/python");
const nginx = option("--nginx") || process.env.RDK_TEST_NGINX || "nginx";
const compose = option("--compose") || process.env.RDK_TEST_COMPOSE;
if (option("--browser")) process.env.RDK_TEST_BROWSER = option("--browser");
function run(bin, args, cwd = root) {
  const r = spawnSync(bin, args, {
    cwd,
    stdio: "inherit",
    timeout: 120000,
    env: process.env,
  });
  if (r.status !== 0)
    throw new Error(`${bin} failed (${r.status}): ${r.error || ""}`);
}
const dashboardPort = 18088;
const backendPort = 18089;
process.env.RDK_QA_DASHBOARD_PORT = String(dashboardPort);
process.env.RDK_QA_BASE_URL = `http://127.0.0.1:${dashboardPort}`;
const tmp = mkdtempSync(join(tmpdir(), "rdk-qa-"));
writeFileSync(
  join(tmp, "mime.types"),
  "types { text/html html; text/css css; application/javascript js; image/svg+xml svg; image/png png; }",
);
for (const filename of ["nginx.conf", "nginx.lan.conf"]) {
  const config = readFileSync(join(root, "frontend", filename), "utf8")
    .replaceAll("/etc/nginx/mime.types", join(tmp, "mime.types"))
    .replaceAll("/usr/share/nginx/html", join(root, "frontend/dist"))
    .replaceAll("/tmp/nginx.pid", join(tmp, "nginx.pid"))
    .replaceAll(":8088", `:${dashboardPort}`)
    .replaceAll(":8089", `:${backendPort}`);
  writeFileSync(join(tmp, filename), config);
}
const children = [];
process.on("SIGINT", async () => { await stopOwned(children); process.exit(130); });
process.on("SIGTERM", async () => { await stopOwned(children); process.exit(143); });
try {
  if (!process.argv.includes("--backend-only")) await assertPortsFree([dashboardPort, backendPort]);
  run(python, ["-m", "pytest", "-q", "-o", "faulthandler_timeout=20"]);
  run(python, ["-m", "ruff", "check", "backend", "scripts", "tests"]);
  run(python, ["-m", "compileall", "-q", "backend", "scripts"]);
  for (const filename of readdirSync(join(root, "scripts")).filter((n) =>
    n.endsWith(".sh"),
  ))
    run("bash", ["-n", join(root, "scripts", filename)]);
  if (!process.argv.includes("--backend-only")) {
    if (compose) {
      run(compose, ["-f", "compose.yaml", "config", "-q"]);
      run(python, ["tests/integration/validate_compose.py", compose]);
    }
    for (const filename of ["nginx.conf", "nginx.lan.conf"])
      run(nginx, ["-t", "-c", join(tmp, filename), "-p", tmp + "/"]);
    const mockConfig = JSON.parse(
      readFileSync(join(root, "config/mock.yaml"), "utf8"),
    );
    mockConfig.allowed_origins = mockConfig.allowed_origins.map((origin) =>
      origin.replace(":8088", `:${dashboardPort}`),
    );
    const configPath = join(tmp, "mock.json");
    writeFileSync(configPath, JSON.stringify(mockConfig));
    const env = { ...process.env, RDK_CONFIG: configPath };
    const backend = startOwned(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(backendPort), "--no-proxy-headers"], { cwd: join(root, "backend"), env, stdio: ["ignore", "inherit", "inherit"] });
    children.push({ child: backend, port: backendPort, name: "backend" });
    const proxy = startOwned(nginx, ["-c", join(tmp, "nginx.conf"), "-p", tmp + "/", "-g", "daemon off;"], { stdio: ["ignore", "inherit", "inherit"] });
    children.push({ child: proxy, port: dashboardPort, name: "nginx" });
    await waitForServices(children, `http://127.0.0.1:${dashboardPort}/api/v1/health`);
    await runGuarded(python, ["tests/integration/live_checks.py"], { cwd: root, stdio: "inherit", env: process.env }, children);
    await runGuarded("node", ["node_modules/@playwright/test/cli.js", "test"], { cwd: join(root, "frontend"), stdio: "inherit", env: process.env }, children);
  } else {
    console.log("Backend-only verification complete");
  }
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  await stopOwned(children);
}
