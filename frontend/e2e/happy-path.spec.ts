/**
 * Phase 1 acceptance, end to end through the browser:
 * investigator creates a case and uploads a questioned image + reference →
 * Tier 1 triage appears (blurred until revealed) → examiner runs Tier 2 source
 * matching and records a conclusion → a different supervisor approves →
 * examiner exports the PDF and its SHA-256 matches the report register.
 */
import { createHash, createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Browser, type Locator, type Page } from "@playwright/test";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const FIXTURES = path.join(ROOT, "backend/tests/fixtures");

function credentials(): Record<string, { password: string; totp: string }> {
  const file = readFileSync(path.join(ROOT, "infra/demo-credentials.txt"), "utf8");
  const out: Record<string, { password: string; totp: string }> = {};
  for (const line of file.split("\n")) {
    if (!line || line.startsWith("#")) continue;
    const [user, ...fields] = line.split("\t");
    const kv = Object.fromEntries(fields.map((f) => [f.slice(0, f.indexOf("=")), f.slice(f.indexOf("=") + 1)]));
    out[user] = { password: kv.password, totp: kv.totp_raw };
  }
  return out;
}

/** RFC 6238 TOTP (HMAC-SHA1, 6 digits, 30 s) using Keycloak's raw secret bytes. */
function totp(secret: string, at = Date.now()): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const h = createHmac("sha1", Buffer.from(secret, "utf8")).update(counter).digest();
  const o = h[h.length - 1] & 0xf;
  const code = ((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3];
  return String(code % 1_000_000).padStart(6, "0");
}

async function pickOption(select: Locator, text: string): Promise<void> {
  const value = await select.locator("option", { hasText: text }).first().getAttribute("value");
  await select.selectOption(value ?? "");
}

/** Every console message that reports a Content-Security-Policy violation. */
const cspViolations: string[] = [];
/** Every request the app makes to anything other than its own origin. */
const foreignRequests: string[] = [];

async function loginAs(browser: Browser, username: string): Promise<Page> {
  const creds = credentials()[username];
  const page = await (await browser.newContext({ ignoreHTTPSErrors: true, acceptDownloads: true })).newPage();
  page.on("console", (m) => {
    if (/content security policy|refused to (load|execute|connect|evaluate)/i.test(m.text())) cspViolations.push(m.text());
  });
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (!["blob:", "data:"].includes(u.protocol) && u.origin !== new URL(page.url() || "https://localhost:8443").origin
        && u.hostname !== "localhost") foreignRequests.push(r.url());
  });
  await page.goto("/");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(creds.password);
  await page.locator("#kc-login").click();
  await page.locator("#otp").fill(totp(creds.totp));
  await page.locator("#kc-login").click();
  await expect(page.getByTestId("whoami")).toContainText(username.split(".")[0], { ignoreCase: true });
  return page;
}

test("upload → triage → conclusion → approval → verified PDF", async ({ browser }) => {
  const caseNo = `E2E/${Date.now()}`;

  // --- Investigator: case + evidence -------------------------------------------
  const ivan = await loginAs(browser, "ivan.investigator");
  await ivan.getByRole("button", { name: "New case" }).click();
  await ivan.locator("#case_no").fill(caseNo);
  await ivan.locator("#crime_head").fill("IT Act s.66E (e2e)");
  await ivan.locator("#io").fill("SI Playwright");
  await ivan.getByRole("button", { name: "Create case" }).click();
  await expect(ivan.getByRole("heading", { name: `Case ${caseNo}` })).toBeVisible();
  const caseUrl = ivan.url();

  await ivan.getByTestId("file-input").setInputFiles(path.join(FIXTURES, "scene_edited.jpg"));
  await ivan.getByTestId("upload-button").click();
  await expect(ivan.getByTestId("upload-result")).toContainText("matches the hash computed in your browser");
  const expectedSha = createHash("sha256").update(readFileSync(path.join(FIXTURES, "scene_edited.jpg"))).digest("hex");
  await expect(ivan.getByTestId("evidence-scene_edited.jpg").getByText(expectedSha, { exact: true })).toBeVisible();

  await ivan.getByTestId("kind-select").selectOption("reference");
  await ivan.getByTestId("reference-for").selectOption({ label: "scene_edited.jpg" });
  await ivan.getByTestId("file-input").setInputFiles(path.join(FIXTURES, "scene_original.jpg"));
  await ivan.getByTestId("upload-button").click();
  await expect(ivan.getByTestId("upload-result")).toContainText("matches the hash computed in your browser");

  // Accounts are mirrored from Keycloak on first login, so these users sign in first.
  const esha = await loginAs(browser, "esha.examiner");
  const sara = await loginAs(browser, "sara.supervisor");

  // A supervisor assigns a second supervisor (approver) and the examiner to the case.
  const suku = await loginAs(browser, "suku.supervisor");
  await suku.goto(caseUrl);
  await pickOption(suku.getByTestId("member-user"), "Sara");
  await suku.getByTestId("member-permission").selectOption("approve");
  await suku.getByRole("button", { name: "Add", exact: true }).click();
  await expect(suku.getByText("Sara Supervisor (sara.supervisor)")).toBeVisible();
  await pickOption(suku.getByTestId("member-user"), "Esha");
  await suku.getByTestId("member-permission").selectOption("analyse");
  await suku.getByRole("button", { name: "Add", exact: true }).click();
  await expect(suku.getByText("Esha Examiner (esha.examiner)")).toBeVisible();

  // --- Examiner: workbench ------------------------------------------------------
  await esha.goto(caseUrl);
  await esha.getByTestId("evidence-scene_edited.jpg").getByRole("link", { name: "Open workbench" }).click();
  await expect(esha.getByTestId("no-verdict-notice")).toContainText("not determinations");
  // Summary tab first: integrity, screening and the results chart.
  await expect(esha.getByTestId("integrity-status")).toContainText("Verified");
  await expect(esha.getByTestId("screening-headline")).toBeVisible();
  await expect(esha.getByTestId("screening-caveat")).toContainText("NOT A FINDING");
  await esha.getByTestId("tab-findings").click();
  await expect(esha.getByTestId("module-image.ela").getByText("succeeded")).toBeVisible({ timeout: 120_000 });
  await expect(esha.getByTestId("module-integrity.hash").getByText("sha256_match")).toBeVisible();
  // Evidence is blurred until explicitly revealed.
  await expect(esha.getByText("Blurred by default").first()).toBeVisible();
  await esha.getByTestId("reveal-image").click();

  await esha.getByTestId("run-image.source_match").click();
  await expect(esha.getByTestId("module-image.source_match").getByText("succeeded")).toBeVisible({ timeout: 120_000 });
  await expect(esha.getByTestId("module-image.source_match").getByText("inlier_count")).toBeVisible();

  await esha.getByTestId("tab-conclusion").click();
  await esha.getByTestId("conclusion-scale").selectOption("moderate_support_manipulation");
  await esha.getByTestId("conclusion-rationale").fill(
    "Source matching against the complainant's original localises two changed regions; noise map agrees.");
  await esha.getByTestId("conclusion-submit").click();
  await expect(esha.getByTestId("latest-conclusion")).toContainText("awaiting supervisor approval");

  // --- Supervisor (not the author) approves --------------------------------------
  await sara.goto("/approvals");
  await sara.getByTestId("approve-button").first().click();
  await expect(sara.getByText("Nothing pending.")).toBeVisible();

  // --- Examiner exports the final report -----------------------------------------
  await esha.goto(`${caseUrl}/report`);
  await esha.getByTestId("generate-report").click();
  await expect(esha.getByTestId("report-case-v1")).toContainText("final");
  const download = esha.waitForEvent("download");
  await esha.getByTestId("report-case-v1").getByRole("button", { name: "Download PDF" }).click();
  const file = await (await download).path();
  const pdf = readFileSync(file);
  expect(pdf.subarray(0, 4).toString()).toBe("%PDF");
  await expect(esha.getByTestId("pdf-hash-check")).toContainText("matches the register");
  const pdfSha = createHash("sha256").update(pdf).digest("hex");
  await expect(esha.getByTestId("report-case-v1")).toContainText(pdfSha);

  // --- Separate report for each evidence item ------------------------------------
  await esha.getByTestId("generate-per-item").click();
  await expect(esha.getByTestId("per-item-result")).toContainText("report(s) generated");
  await expect(esha.locator('[data-testid^="report-"][data-testid$="-v1"]').filter({ hasText: "final" })).toHaveCount(2);

  // --- Video upload and analysis ---------------------------------------------------
  await ivan.goto(caseUrl);
  await ivan.getByRole("button", { name: "Add evidence" }).click();
  await ivan.getByTestId("file-input").setInputFiles(path.join(FIXTURES, "scene_video.mp4"));
  await ivan.getByTestId("upload-button").click();
  await expect(ivan.getByTestId("upload-result")).toContainText("matches the hash computed in your browser");
  await ivan.getByTestId("evidence-scene_video.mp4").getByRole("link", { name: "Open workbench" }).click();
  await expect(ivan.getByTestId("integrity-status")).toContainText("Verified");
  await ivan.getByTestId("reveal-video").click();
  await expect(ivan.getByTestId("video-player")).toBeVisible();
  await ivan.getByTestId("tab-findings").click();
  await expect(ivan.getByTestId("module-video.container").getByText("succeeded")).toBeVisible({ timeout: 120_000 });
  await expect(ivan.getByTestId("module-video.container").getByText("reencode_indicator")).toBeVisible();
  await expect(ivan.getByTestId("screening-headline")).toBeVisible();

  // --- Bulk upload (FR-1.8): several files at once, each hashed and triaged ----------
  await ivan.goto(caseUrl);
  await ivan.getByRole("button", { name: "Add evidence" }).click();
  await ivan.getByTestId("file-input").setInputFiles([path.join(FIXTURES, "scene_original.png"), path.join(FIXTURES, "tone.wav")]);
  await ivan.getByTestId("upload-button").click();
  await expect(ivan.getByTestId("upload-result")).toHaveCount(2, { timeout: 60_000 });
  await expect(ivan.getByTestId("evidence-tone.wav")).toBeVisible();

  // --- Malayalam labels for investigator screens (NFR-U4) --------------------------
  await ivan.getByTestId("lang-toggle").click();
  await expect(ivan.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "കേസുകൾ" })).toBeVisible();
  await ivan.getByTestId("lang-toggle").click();
  await expect(ivan.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Cases" })).toBeVisible();

  // --- Audit chain still verifies ------------------------------------------------
  await suku.goto("/admin");
  await suku.getByRole("tab", { name: "Audit chain" }).click();
  await suku.getByTestId("verify-audit").click();
  await expect(suku.getByTestId("audit-ok")).toContainText("Intact");

  // --- Air-gap at the browser: nothing loaded from elsewhere, nothing blocked by CSP ---
  expect(foreignRequests, "requests to other origins").toEqual([]);
  expect(cspViolations, "CSP violations").toEqual([]);
});
