// Linux QA process and socket ownership checks. Never signal processes we did not spawn.
import net from "node:net";
import { readdirSync, readFileSync, readlinkSync } from "node:fs";
import { spawn } from "node:child_process";

export async function assertPortsFree(ports) {
  for (const port of ports) {
    for (const [host, ipv6Only] of [["127.0.0.1", false], ["::1", true]]) {
      const server = net.createServer();
      await new Promise((resolve, reject) => {
        server.once("error", (error) => reject(new Error(`QA port ${port} unavailable (${host}): ${error.message}`)));
        server.listen({ host, port, exclusive: true, ipv6Only }, () => server.close(resolve));
      });
    }
  }
}

export function listeningInodes(port) {
  const found = new Set();
  for (const file of ["/proc/net/tcp", "/proc/net/tcp6"]) {
    for (const line of readFileSync(file, "utf8").trim().split("\n").slice(1)) {
      const fields = line.trim().split(/\s+/);
      if (fields[3] === "0A" && parseInt(fields[1].split(":")[1], 16) === port) found.add(fields[9]);
    }
  }
  return found;
}

export function ownsListener(child, port) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return false;
  const inodes = listeningInodes(port);
  if (inodes.size !== 1) return false;
  try {
    return readdirSync(`/proc/${child.pid}/fd`).some((fd) => {
      try { const m = /^socket:\[(\d+)\]$/.exec(readlinkSync(`/proc/${child.pid}/fd/${fd}`)); return m && inodes.has(m[1]); }
      catch { return false; }
    });
  } catch { return false; }
}

export function assertOwned(children) {
  for (const { child, port, name } of children) {
    if (!ownsListener(child, port)) throw new Error(`${name} child does not own the QA listener on port ${port}`);
  }
}

export async function waitForServices(children, healthUrl, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const { child, name } of children) {
      if (child.spawnFailure || child.exitCode !== null || child.signalCode !== null)
        throw new Error(`${name} child failed during startup: ${child.spawnFailure || child.exitCode || child.signalCode}`);
    }
    if (children.every(({ child, port }) => ownsListener(child, port))) {
      try {
        const response = await fetch(healthUrl, { signal: AbortSignal.timeout(1000) });
        if (response.ok) { assertOwned(children); return; }
      } catch { /* wait for backend */ }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("QA services failed startup, ownership, or readiness checks");
}

export function startOwned(bin, args, options = {}) {
  const child = spawn(bin, args, options);
  child.spawnFailure = null;
  child.on("error", (err) => { child.spawnFailure = err.message; });
  return child;
}

export async function runGuarded(bin, args, options, children) {
  assertOwned(children);
  const child = startOwned(bin, args, { ...options, detached: true });
  const signalGroup = (signal) => {
    if (!child.pid) return;
    try { process.kill(-child.pid, signal); } catch (error) { if (error.code !== "ESRCH") throw error; }
  };
  let killTimer;
  const stopGroup = () => {
    if (child.guardFailed && killTimer) return;
    child.guardFailed = true;
    signalGroup("SIGTERM");
    killTimer = setTimeout(() => signalGroup("SIGKILL"), 3000);
  };
  process.on("SIGINT", stopGroup);
  process.on("SIGTERM", stopGroup);
  const code = await new Promise((resolve) => {
    const deadline = setTimeout(stopGroup, 120000);
    const timer = setInterval(() => {
      try { assertOwned(children); } catch { stopGroup(); }
    }, 200);
    const finish = (status) => {
      clearInterval(timer); clearTimeout(deadline); clearTimeout(killTimer);
      process.off("SIGINT", stopGroup); process.off("SIGTERM", stopGroup);
      if (child.guardFailed) signalGroup("SIGKILL");
      resolve(status);
    };
    child.once("error", () => finish(null));
    child.once("close", finish);
  });
  assertOwned(children);
  if (child.guardFailed || code !== 0) throw new Error(`${bin} failed or QA service ownership was lost (${code})`);
}

export async function stopOwned(children) {
  for (const { child } of children) if (child.exitCode === null && child.signalCode === null && child.pid) child.kill("SIGTERM");
  await Promise.all(children.map(({ child }) => new Promise((resolve) => {
    if (!child.pid || child.exitCode !== null || child.signalCode !== null) return resolve();
    const timer = setTimeout(() => { if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL"); resolve(); }, 3000);
    child.once("close", () => { clearTimeout(timer); resolve(); });
  })));
}
