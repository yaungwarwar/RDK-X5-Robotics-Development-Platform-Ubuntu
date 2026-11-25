// Unified local QA. No target access; child ownership is checked by qa_process_guard.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { accessSync, constants, existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { assertPortsFree, listeningInodes, ownsListener, runGuarded, startOwned, stopOwned, waitForServices } from "./qa_process_guard.mjs";
import { browserStats, requireBrowserPass, requireUnchanged } from "./qa_full_checks.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const frontend = join(root, "frontend");
const output = resolve(process.env.RDK_QA_OUTPUT || join(root, "qa-results"));
mkdirSync(output, { recursive: true });
const reportPath = join(output, "qa-report.json");
const runOutput = join(output, `run-${Date.now()}-${process.pid}`);
mkdirSync(runOutput, { recursive: true });
const report = { started_at: new Date().toISOString(), completed_at: null, result: "running", tools: {}, stages: [], optional_checks: [], tests: {}, artifacts: {}, listeners: {}, cleanup: {}, warnings: [] };
const env = { ...process.env };
delete env.PYTHONHOME;
delete env.PYTHONPATH;
const python = env.RDK_QA_PYTHON || join(root, ".venv-recovered/bin/python");
const nginx = env.RDK_QA_NGINX || join(root, ".venv-qa-tools/nginx/usr/sbin/nginx");
const compose = env.RDK_QA_COMPOSE || join(root, ".venv-qa-tools/bin/docker-compose");
const wheels = env.RDK_QA_WHEELS || join(root, ".venv-qa-tools/wheels");
const browserRoot = join(env.HOME || "", ".cache/ms-playwright");
const chromium = env.RDK_QA_CHROMIUM || (existsSync(browserRoot) ? readdirSync(browserRoot).filter((x) => /^chromium-\d+$/.test(x)).sort().reverse().map((x) => join(browserRoot, x, "chrome-linux64/chrome")).find(existsSync) : null);
const artifactFiles = {
  "release/rdk-control-center-0.1.3.tar.gz": "07cf0439383e6fc207ca47517ffeb62f56603be4fb136e08f42e15c31e6cd37b",
  "release/rdk-control-center-0.1.3-source-manifest.sha256": "aa0a8a7d724403344559d5df2da2d8cae69b469d1f341c812431b86cd1fa3f76",
  ".venv-qa-tools/camera-b1/camera-lab-b1.tar.gz": "a5fe70addced98c8829650b644a79887f8d7c6b993b6473c9ab6c8e933cdf201",
  ".venv-qa-tools/camera-b1/camera-lab-b1-nv12.tar.gz": "42c6b98f2fb3b421504f5e13e2e2357f2ada8f7403ecadfcc4292a988e4332b1",
  ".venv-qa-tools/camera-b1/camera-lab-b1-nv12-reconnect.tar.gz": "71b3a00a8a2afab1f686d478eacccb1a1b9fca227beb46b3a765546bdd1aa7e3",
};
function hash(data) { return createHash("sha256").update(data).digest("hex"); }
function outputAndWarnings(stream, data) {
  (stream === "stderr" ? process.stderr : process.stdout).write(data);
  for (const line of data.toString().split("\n")) if (/warning/i.test(line) && report.warnings.length < 30) report.warnings.push(line.slice(0, 300));
}
function treeHash(paths) {
  const entries = [];
  function visit(path) {
    if (!existsSync(path)) throw new Error(`Missing build input/output: ${path}`);
    if (statSync(path).isDirectory()) {
      for (const name of readdirSync(path).sort()) visit(join(path, name));
    } else entries.push([path.slice(root.length + 1), hash(readFileSync(path))]);
  }
  paths.forEach(visit);
  return hash(JSON.stringify(entries));
}
function command(bin, args, cwd = root, extraEnv = {}) {
  const result = spawnSync(bin, args, { cwd, env: { ...env, ...extraEnv }, encoding: "utf8", maxBuffer: 32 * 1024 * 1024, timeout: 180000 });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  for (const line of (result.stdout + "\n" + result.stderr).split("\n")) {
    if (/warning/i.test(line) && report.warnings.length < 30) report.warnings.push(line.slice(0, 300));
  }
  if (result.error || result.status !== 0) {
    const error = new Error(`${bin} failed (exit ${result.status}, ${result.error?.code || result.signal || "failure"})`);
    error.exitCode = result.status;
    throw error;
  }
  return result.stdout;
}
async function stage(name, fn) {
  const item = { name, required: true, started_at: new Date().toISOString(), duration_seconds: null, exit_code: null, status: "running" };
  report.stages.push(item);
  const start = performance.now();
  process.stdout.write(`\n[QA] ${name}\n`);
  try { await fn(); item.status = "passed"; item.exit_code = 0; }
  catch (error) { item.status = "failed"; item.exit_code = error.exitCode ?? 1; item.error = String(error.message).slice(0, 500); throw error; }
  finally { item.duration_seconds = Math.round(performance.now() - start) / 1000; }
}
function readBrowserStats(file) { return browserStats(JSON.parse(readFileSync(file, "utf8"))); }
const sourcePaths = ["src", "camera-lab/main.tsx", "camera-lab/style.css", "camera-lab/index.html", "camera-lab/vite.config.ts", "camera-lab/playwright.config.ts", "camera-lab/tsconfig.json", "camera-lab/tests", "tests", "public", "index.html", "vite.config.ts", "playwright.config.ts", "eslint.config.js", "tsconfig.json", "package.json", "package-lock.json"].map((p) => join(frontend, p));
const distPaths = [join(frontend, "dist"), join(root, "prototype/camera_lab/dist")];
let labChild;
try {
  await stage("preflight", async () => {
    for (const [name, path] of Object.entries({ python, nginx, compose, chromium })) {
      if (!path || !isAbsolute(path) || !existsSync(path)) throw new Error(`Required ${name} executable is unavailable`);
      accessSync(path, constants.X_OK);
    }
    if (!existsSync(wheels) || !statSync(wheels).isDirectory()) throw new Error("Persistent wheel cache is unavailable");
    if (!readdirSync(wheels).some((name) => name.endsWith(".whl"))) throw new Error("Persistent wheel cache is empty");
    if (!existsSync(join(frontend, "node_modules/@playwright/test/cli.js"))) throw new Error("Frontend dependencies are unavailable");
    await assertPortsFree([18088, 18089, 18100]);
    report.tools.python = command(python, ["--version"]).trim();
    report.tools.pip = command(python, ["-m", "pip", "--version"]).trim();
    report.tools.pytest = command(python, ["-m", "pytest", "--version"]).trim();
    report.tools.ruff = command(python, ["-m", "ruff", "--version"]).trim();
    report.tools.node = command("node", ["--version"]).trim();
    report.tools.npm = command("npm", ["--version"]).trim();
    const nginxVersion = spawnSync(nginx, ["-v"], { encoding: "utf8" });
    if (nginxVersion.status !== 0) throw new Error("Nginx version check failed");
    report.tools.nginx = nginxVersion.stderr.trim();
    report.tools.compose = command(compose, ["version", "--short"]).trim();
    report.tools.chromium = command(chromium, ["--version"]).trim();
    report.tools.typescript = command("node_modules/.bin/tsc", ["--version"], frontend).trim();
    report.tools.vite = command("node_modules/.bin/vite", ["--version"], frontend).trim();
    report.tools.eslint = command("node_modules/.bin/eslint", ["--version"], frontend).trim();
    report.tools.playwright = command("node", ["node_modules/@playwright/test/cli.js", "--version"], frontend).trim();
    if (!report.tools.nginx) throw new Error("Nginx version unavailable");
  });
  await stage("immutable_artifacts", () => {
    for (const [path, expected] of Object.entries(artifactFiles)) {
      const actual = hash(readFileSync(join(root, path)));
      report.artifacts[path] = { sha256: actual, expected, matches: actual === expected };
      if (actual !== expected) throw new Error(`Artifact integrity mismatch: ${path}`);
    }
  });
  await stage("dependency_validation", () => command(python, ["-m", "pip", "check"]));
  await stage("python_static", () => {
    command(python, ["-m", "ruff", "check", "backend", "scripts", "tests", "prototype/camera_lab"]);
    command(python, ["-m", "ruff", "format", "--check", "backend", "scripts", "tests", "prototype/camera_lab"]);
    command(python, ["-m", "compileall", "-q", "backend", "scripts", "prototype/camera_lab"]);
  });
  await stage("python_tests", () => {
    const xml = join(runOutput, "python-junit.xml");
    let failure;
    try { command(python, ["-m", "pytest", "-q", `--junitxml=${xml}`]); } catch (error) { failure = error; }
    if (!existsSync(xml)) throw failure || new Error("Python test report missing");
    const code = "import json,sys,xml.etree.ElementTree as E; x=E.parse(sys.argv[1]).getroot(); s=x.find('testsuite') if x.tag!='testsuite' else x; print(json.dumps({k:int(s.get(k,'0')) for k in ('tests','failures','errors','skipped')}))";
    const counts = JSON.parse(command(python, ["-c", code, xml]).trim());
    counts.passed = counts.tests - counts.failures - counts.errors - counts.skipped;
    report.tests.python = counts;
    if (failure) throw failure;
    if (!counts.tests || counts.failures || counts.errors || counts.skipped) throw new Error("Required Python tests failed, skipped or absent");
  });
  let sources, built;
  await stage("frontend_static_and_fresh_builds", () => {
    sources = treeHash(sourcePaths);
    command("npm", ["run", "lint"], frontend);
    command("npm", ["run", "typecheck"], frontend);
    command("node_modules/.bin/eslint", ["camera-lab"], frontend);
    command("node_modules/.bin/tsc", ["--noEmit", "-p", "camera-lab/tsconfig.json"], frontend);
    command("node_modules/.bin/prettier", ["--check", "src/telemetry.ts", "src/main.tsx", "tests/dashboard.spec.ts", "camera-lab/main.tsx", "camera-lab/tests/lab.spec.ts"], frontend);
    command("npm", ["run", "build"], frontend);
    command("node_modules/.bin/vite", ["build", "--config", "camera-lab/vite.config.ts"], frontend);
    requireUnchanged(sources, treeHash(sourcePaths), "Frontend source changed during build");
    built = treeHash(distPaths);
    report.build = { source_sha256: sources, output_sha256: built };
  });
  await stage("dashboard_proxy_compose_and_browser", () => {
    const json = join(runOutput, "dashboard-playwright.json");
    const evidence = join(runOutput, "proxy-ownership.json");
    try {
      command("node", ["scripts/verify_local.mjs", "--skip-python", "--python", python, "--nginx", nginx, "--compose", compose, "--browser", chromium], root, { PLAYWRIGHT_JSON_OUTPUT_FILE: json, RDK_QA_PROXY_EVIDENCE: evidence });
      report.tests.dashboard = readBrowserStats(json);
      requireBrowserPass(report.tests.dashboard);
    } finally {
      if (existsSync(evidence)) report.listeners.dashboard = JSON.parse(readFileSync(evidence, "utf8"));
      if (!report.tests.dashboard && existsSync(json)) { try { report.tests.dashboard = readBrowserStats(json); } catch { /* failure recorded by stage */ } }
    }
  });
  await stage("laboratory_browser_and_ownership", async () => {
    const port = 18100;
    const children = [];
    let preflight = false;
    try {
      await assertPortsFree([port]); preflight = true;
      labChild = startOwned(python, ["prototype/camera_lab/server.py"], { cwd: root, env, stdio: ["ignore", "inherit", "inherit"] });
      children.push({ child: labChild, port, name: "camera laboratory" });
      await waitForServices(children, `http://127.0.0.1:${port}/lab/status`);
      const index = readFileSync(join(root, "prototype/camera_lab/dist/camera-lab/index.html"));
      const response = Buffer.from(await (await fetch(`http://127.0.0.1:${port}/`)).arrayBuffer());
      if (!index.equals(response)) throw new Error("Lab is not serving the freshly built frontend");
      const asset = /src="(\/assets\/[^"?#]+\.js)"/.exec(index.toString())?.[1];
      if (!asset) throw new Error("Built lab JavaScript asset missing");
      const expected = readFileSync(join(root, "prototype/camera_lab/dist", asset));
      const served = Buffer.from(await (await fetch(`http://127.0.0.1:${port}${asset}`)).arrayBuffer());
      if (!expected.equals(served)) throw new Error("Lab JavaScript differs from build");
      report.listeners.laboratory = { port, pid: labChild.pid, inodes: [...listeningInodes(port)], owned: ownsListener(labChild, port), servedSha256: hash(served) };
      const json = join(runOutput, "laboratory-playwright.json");
      try {
        await runGuarded("node", ["node_modules/@playwright/test/cli.js", "test", "--config", "camera-lab/playwright.config.ts", "--reporter=list,json"], { cwd: frontend, stdio: ["ignore", "pipe", "pipe"], onOutput: outputAndWarnings, env: { ...env, RDK_LAB_EXTERNAL: "1", RDK_TEST_BROWSER: chromium, RDK_TEST_PYTHON: python, PLAYWRIGHT_JSON_OUTPUT_FILE: json } }, children);
      } finally { if (existsSync(json)) report.tests.laboratory = readBrowserStats(json); }
      if (!report.tests.laboratory) throw new Error("Lab browser report missing");
      requireBrowserPass(report.tests.laboratory);
    } finally {
      await stopOwned(children);
      const exited = !labChild || labChild.exitCode !== null || labChild.signalCode !== null;
      const clear = listeningInodes(port).size === 0;
      report.cleanup.laboratory = { preflight, exited, port_clear: clear };
      if (!exited || (preflight && !clear)) throw new Error("Laboratory process or listener cleanup failed");
    }
  });
  await stage("final_integrity", () => {
    requireUnchanged(sources, treeHash(sourcePaths), "Frontend source changed during tests");
    requireUnchanged(built, treeHash(distPaths), "Frontend build changed during tests");
    for (const [path, expected] of Object.entries(artifactFiles)) if (hash(readFileSync(join(root, path))) !== expected) throw new Error(`Artifact changed during QA: ${path}`);
  });
  report.result = "passed";
} catch (error) {
  report.result = "failed";
  report.error = String(error.message).slice(0, 500);
  process.stderr.write(`QA failed: ${report.error}\n`);
  process.exitCode = 1;
} finally {
  const requiredStages = ["preflight", "immutable_artifacts", "dependency_validation", "python_static", "python_tests", "frontend_static_and_fresh_builds", "dashboard_proxy_compose_and_browser", "laboratory_browser_and_ownership", "final_integrity"];
  for (const name of requiredStages) if (!report.stages.some((stage) => stage.name === name)) report.stages.push({ name, required: true, status: "not_run", exit_code: null, duration_seconds: null });
  report.detail_directory = runOutput;
  report.completed_at = new Date().toISOString();
  writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
  process.stdout.write(`QA report: ${reportPath}\n`);
}
