// Synthetic images arrive only via stdin; no image file is written.
import { createRequire } from "node:module";
const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("@playwright/test");
let data = "";
for await (const chunk of process.stdin) data += chunk;
const browser = await chromium.launch({ executablePath: process.env.RDK_TEST_BROWSER, headless: true });
try {
  const page = await browser.newPage();
  const result = await page.evaluate(async (encoded) => {
    const img = new Image();
    img.src = `data:image/png;base64,${encoded}`;
    await img.decode();
    return { success: true, width: img.naturalWidth, height: img.naturalHeight };
  }, data);
  process.stdout.write(JSON.stringify(result));
} finally { await browser.close(); }
