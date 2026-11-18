/**
 * Visual review helper (not part of the acceptance suite): signs in as each role and
 * saves full-page screenshots of every screen to test-results/screens/.
 * Run: SAFEFACE_SCREENS=1 npx playwright test screens
 */
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, type Browser, type Page } from "@playwright/test";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const OUT = path.join(ROOT, "frontend/test-results/screens");

function creds(user: string): { password: string; totp: string } {
  const line = readFileSync(path.join(ROOT, "infra/demo-credentials.txt"), "utf8").split("\n").find((l) => l.startsWith(user + "\t"))!;
  const kv = Object.fromEntries(line.split("\t").slice(1).map((f) => [f.slice(0, f.indexOf("=")), f.slice(f.indexOf("=") + 1)]));
  return { password: kv.password, totp: kv.totp_raw };
}

function totp(secret: string): string {
  const c = Buffer.alloc(8);
  c.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const h = createHmac("sha1", Buffer.from(secret, "utf8")).update(c).digest();
  const o = h[h.length - 1] & 0xf;
  return String((((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3]) % 1_000_000).padStart(6, "0");
}

async function login(browser: Browser, user: string): Promise<Page> {
  const page = await (await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } })).newPage();
  const c = creds(user);
  await page.goto("/");
  await page.locator("#username").fill(user);
  await page.locator("#password").fill(c.password);
  await page.locator("#kc-login").click();
  await page.locator("#otp").fill(totp(c.totp));
  await page.locator("#kc-login").click();
  await page.getByTestId("whoami").waitFor();
  return page;
}

async function shot(page: Page, name: string, url?: string) {
  if (url) {
    await page.goto(url);
    await page.getByTestId("whoami").waitFor();
  }
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
}

test.skip(!process.env.SAFEFACE_SCREENS, "visual review only");

test("screens", async ({ browser }) => {
  test.setTimeout(300_000);
  const esha = await login(browser, "esha.examiner");
  await shot(esha, "examiner-home");
  await esha.getByRole("link", { name: "DEMO/2026/0001" }).click();
  await shot(esha, "examiner-case");
  const caseUrl = esha.url();
  await esha.getByRole("link", { name: "Open workbench" }).first().click();
  await esha.getByTestId("module-panel").waitFor();
  await shot(esha, "examiner-workbench");
  await shot(esha, "examiner-report", `${caseUrl}/report`);
  await shot(esha, "examiner-admin", "/admin");

  const ivan = await login(browser, "ivan.investigator");
  await shot(ivan, "investigator-home");
  const adam = await login(browser, "adam.admin");
  await shot(adam, "admin-home");
  await shot(adam, "admin-admin", "/admin");
  const suku = await login(browser, "suku.supervisor");
  await shot(suku, "supervisor-home");
  await shot(suku, "supervisor-approvals", "/approvals");
  await shot(suku, "supervisor-audit", "/audit");
  const audrey = await login(browser, "audrey.auditor");
  await shot(audrey, "auditor-home");
});
