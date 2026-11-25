// Pure fail-closed checks shared by the unified runner and focused regressions.
export function browserStats(report) {
  const s = report.stats;
  if (!s || ![s.expected, s.unexpected, s.skipped, s.flaky].every((n) => Number.isInteger(n) && n >= 0)) throw new Error("Missing browser result counts");
  return { passed: s.expected, failed: s.unexpected, skipped: s.skipped, flaky: s.flaky, total: s.expected + s.unexpected + s.skipped + s.flaky };
}
export function requireBrowserPass(result) {
  if (!result.total || result.failed || result.skipped || result.flaky) throw new Error("Required browser tests failed, skipped, flaky or absent");
}
export function requireUnchanged(before, after, message) {
  if (!before || before !== after) throw new Error(message);
}
