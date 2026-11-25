// One owned QA session: backend tests, native proxy, production UI and browser checks.
import { spawnSync } from "node:child_process";
import { assertPortsFree, startOwned, waitForServices, runGuarded, stopOwned, ownsListener, listeningInodes } from "./qa_process_guard.mjs";
import { mkdtempSync, readFileSync, writeFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
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
    .replaceAll("/dev/stderr", join(tmp, "nginx-error.log"))
    .replaceAll("/usr/share/nginx/html", join(root, "frontend/dist"))
    .replaceAll("/tmp/nginx.pid", join(tmp, "nginx.pid"))
    .replaceAll(":8088", `:${dashboardPort}`)
    .replaceAll(":8089", `:${backendPort}`);
  writeFileSync(join(tmp, filename), config);
}
const children = [];
const evidence = { preflight: false, listeners: [], cleanup: [], portsClear: false };
process.on("SIGINT", async () => { await stopOwned(children); process.exit(130); });
process.on("SIGTERM", async () => { await stopOwned(children); process.exit(143); });
try {
  if (!process.argv.includes("--backend-only")) {
    await assertPortsFree([dashboardPort, backendPort]);
    evidence.preflight = true;
  }
  if (!process.argv.includes("--skip-python")) {
    run(python, ["-m", "pytest", "-q", "-o", "faulthandler_timeout=20"]);
    run(python, ["-m", "ruff", "check", "backend", "scripts", "tests"]);
    run(python, ["-m", "compileall", "-q", "backend", "scripts"]);
  }
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
    evidence.listeners = children.map(({ child, port, name }) => ({ name, port, pid: child.pid, inodes: [...listeningInodes(port)], owned: ownsListener(child, port) }));
    const expectedHtml = readFileSync(join(root, "frontend/dist/index.html"));
    const actualHtml = Buffer.from(await (await fetch(`http://127.0.0.1:${dashboardPort}/`)).arrayBuffer());
    if (!actualHtml.equals(expectedHtml)) throw new Error("Proxy is not serving the freshly built dashboard");
    const asset = /src="(\/assets\/[^"?#]+\.js)"/.exec(expectedHtml.toString())?.[1];
    if (!asset) throw new Error("Built dashboard JavaScript asset missing");
    const expectedAsset = readFileSync(join(root, "frontend/dist", asset));
    const actualAsset = Buffer.from(await (await fetch(`http://127.0.0.1:${dashboardPort}${asset}`)).arrayBuffer());
    if (!actualAsset.equals(expectedAsset)) throw new Error("Proxy dashboard JavaScript differs from build");
    evidence.servedSha256 = createHash("sha256").update(actualAsset).digest("hex");
    await runGuarded(python, ["tests/integration/live_checks.py"], { cwd: root, stdio: "inherit", env: process.env }, children);
    const browserArgs = ["node_modules/@playwright/test/cli.js", "test"];
    if (process.env.PLAYWRIGHT_JSON_OUTPUT_FILE) browserArgs.push("--reporter=list,json");
    await runGuarded("node", browserArgs, { cwd: join(root, "frontend"), stdio: "inherit", env: process.env }, children);
  } else {
    console.log("Backend-only verification complete");
  }
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  await stopOwned(children);
  evidence.cleanup = children.map(({ child, port, name }) => ({ name, port, pid: child.pid, exited: child.exitCode !== null || child.signalCode !== null, owned: ownsListener(child, port) }));
  evidence.portsClear = evidence.preflight && [dashboardPort, backendPort].every((p) => listeningInodes(p).size === 0);
  if (evidence.cleanup.some((x) => !x.exited || x.owned) || (evidence.preflight && !evidence.portsClear)) process.exitCode = 1;
  if (process.env.RDK_QA_PROXY_EVIDENCE) writeFileSync(process.env.RDK_QA_PROXY_EVIDENCE, JSON.stringify(evidence, null, 2));
}
