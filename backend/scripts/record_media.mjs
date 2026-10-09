// Records the portfolio walkthrough: screenshots, a continuous video and the Word outputs.
//
// Prerequisites (from the repo root):
//   cd backend && APP_ENV=local APP_DEMO=1 uvicorn app.main:app --port 8000
//   cd frontend && npm run build && npx vite preview --port 4173
// Run:
//   node backend/scripts/record_media.mjs <out-dir>
// Needs Playwright; set PLAYWRIGHT_MODULE if it is not resolvable from here.

import path from "node:path";
import fs from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const samples = path.resolve(here, "../samples");
const out = path.resolve(process.argv[2] ?? "media-out");
const raw = path.join(out, "raw");
fs.mkdirSync(raw, { recursive: true });

const pwModule = process.env.PLAYWRIGHT_MODULE ?? "playwright";
const { chromium } = await import(pwModule.startsWith("/") ? pathToFileURL(pwModule).href : pwModule);

const W = 1440, H = 900;
const REF = "CRM-004217";
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: W, height: H },
  deviceScaleFactor: 2,
  recordVideo: { dir: raw, size: { width: W, height: H } },
  acceptDownloads: true,
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

// ------------------------------------------------------------------ presentation helpers

async function installOverlay() {
  await page.evaluate(() => {
    const cap = document.createElement("div");
    cap.id = "demo-caption";
    Object.assign(cap.style, {
      position: "fixed", left: "50%", bottom: "28px", transform: "translateX(-50%)", zIndex: 99999,
      background: "rgba(20,26,38,.92)", color: "#fff", font: "600 19px system-ui, sans-serif",
      padding: "12px 22px", borderRadius: "10px", boxShadow: "0 6px 24px rgba(0,0,0,.25)",
      maxWidth: "80%", textAlign: "center", transition: "opacity .25s", opacity: "0", pointerEvents: "none",
    });
    const cur = document.createElement("div");
    cur.id = "demo-cursor";
    Object.assign(cur.style, {
      position: "fixed", left: "720px", top: "450px", width: "22px", height: "22px", zIndex: 100000,
      borderRadius: "50%", background: "rgba(91,44,131,.35)", border: "2px solid #5b2c83",
      transform: "translate(-50%,-50%)", transition: "left .45s ease, top .45s ease", pointerEvents: "none",
    });
    // caption text lives in ::after so it never matches the script's text selectors
    const style = document.createElement("style");
    style.textContent = "#demo-caption::after { content: attr(data-text); }";
    document.head.append(style);
    document.body.append(cap, cur);
  });
}

async function caption(text, hold = 1800) {
  await page.evaluate((t) => {
    const el = document.getElementById("demo-caption");
    el.dataset.text = t;
    el.style.opacity = t ? "1" : "0";
  }, text);
  await page.waitForTimeout(hold);
}

async function pointAt(locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) return;
  await page.evaluate(({ x, y }) => {
    const c = document.getElementById("demo-cursor");
    c.style.left = `${x}px`;
    c.style.top = `${y}px`;
  }, { x: box.x + box.width / 2, y: box.y + box.height / 2 });
  await page.waitForTimeout(550);
}

async function click(locator, pause = 500) {
  await pointAt(locator);
  await locator.click();
  await page.waitForTimeout(pause);
}

async function type(locator, text) {
  await pointAt(locator);
  await locator.click();
  await locator.pressSequentially(text, { delay: 35 });
}

async function shot(name, opts = {}) {
  await page.evaluate(() => {
    for (const id of ["demo-caption", "demo-cursor"]) document.getElementById(id).style.visibility = "hidden";
  });
  await page.screenshot({ path: path.join(out, name), ...opts });
  await page.evaluate(() => {
    for (const id of ["demo-caption", "demo-cursor"]) document.getElementById(id).style.visibility = "visible";
  });
}

async function asUser(user) {
  await click(page.locator("header select"), 200);
  await page.selectOption("header select", user);
  await page.waitForTimeout(500);
}

async function openCase() {
  await click(page.locator("tr", { hasText: REF }).locator("text=Open"));
  await page.waitForSelector("text=Case record");
  await page.waitForTimeout(400);
}

async function recordGap(key, value) {
  await page.selectOption(".panel.gap select", key);
  await type(page.locator('.panel.gap input[placeholder="Value"]'), value);
  await click(page.locator('.panel.gap button:has-text("Record")'), 700);
}

const step = (m) => console.log("step:", m);

// ------------------------------------------------------------------ story

await page.goto("http://localhost:4173");
await installOverlay();
await caption("A paraplanner opens a new client case", 1500);
await type(page.locator('input[placeholder="CRM client reference"]'), REF);
await click(page.locator("text=Create case"));
await openCase();

await caption("Client documents are uploaded: a fact-find and a provider pension statement", 1200);
for (const f of ["fact_find.txt", "pension_statement.txt"]) {
  await page.setInputFiles('input[type="file"]', path.join(samples, f));
  await page.waitForTimeout(700);
}
await page.waitForSelector("text=Conflicting evidence");
await page.evaluate(() => window.scrollTo({ top: 0 }));
await caption("Every value is extracted with a citation to its exact source passage", 2200);
await shot("01-case-record-conflict.png");
step("conflict");

await caption("The two documents disagree on the fund value, so a person must decide (with a reason)", 1500);
await type(page.locator('input[placeholder^="Reason for your choice"]'), "Provider statement (31 March 2026) is more recent");
await click(page.locator(".candidate", { hasText: "£125,400.00" }).locator("text=Use this value"), 900);
await page.waitForSelector("text=Conflicting evidence", { state: "detached" });

await caption("Gaps: information the template requires that no document provides", 1500);
await page.selectOption(".panel.gap select", "client.capacity_for_loss");
await type(page.locator('.panel.gap input[placeholder="Value"]'), "High");
await type(page.locator('.panel.gap input[placeholder^="Note"]'), "Discussed at meeting 2 Sept 2026");
await shot("03-gaps-adviser-input.png");
await click(page.locator('.panel.gap button:has-text("Record")'), 700);

await caption("Only a qualified adviser can record the recommendation and reasons", 900);
await asUser("aaron");
await openCase();
await recordGap("adviser.recommendation", "Transfer to the recommended personal pension");
await recordGap("adviser.reasons", "Lower charges, online access, balanced fund range");
// not a template gap, so recorded through the API (same audited endpoint the UI uses)
await page.evaluate(async (ref) => {
  const h = { "X-Dev-User": "aaron", "Content-Type": "application/json" };
  const cases = await (await fetch("/api/cases", { headers: h })).json();
  const c = cases.find((x) => x.client_ref === ref);
  await fetch(`/api/cases/${c.id}/adviser-inputs`, {
    method: "POST", headers: h,
    body: JSON.stringify({ key: "adviser.recommended_charge_pct", value: "0.55%" }),
  });
}, REF);
step("adviser inputs");

await asUser("alice");
await openCase();
await page.waitForSelector("text=Verify against source");
await caption("Click any fact to see exactly where it came from", 600);
const atr = page.locator("tr", { hasText: "client.attitude_to_risk" });
await click(atr, 900);
await page.waitForSelector("aside mark");
await pointAt(page.locator("aside .source").first());
await caption("Document, page and passage: the evidence behind the value", 1800);
await shot("02-source-evidence.png");

await caption("The paraplanner verifies each extracted fact against its source", 600);
while (await page.locator("text=Verify against source").count()) {
  await click(page.locator("text=Verify against source").first(), 120);
}
await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
await page.waitForTimeout(500);
step("verified");

await caption("The draft is written from verified facts only, never from the raw documents", 900);
await click(page.locator("text=Generate draft report"), 900);
await page.waitForSelector("text=Verification findings");
await caption("Verifier: every sentence must cite facts, and every figure must match them", 1800);
const stmt = page.locator(".statement", { hasText: "£125,400.00" });
await click(stmt, 900);
await page.waitForSelector("aside mark");
await caption("Each AI-drafted sentence links to the facts and source passages it relies on", 2200);
await shot("04-report-review.png");
step("draft");

await click(page.locator("text=Submit for review"), 800);
await caption("A different person must review and approve (maker-checker)", 900);
await asUser("bob");
await openCase();
await click(page.locator("button", { hasText: "Open rpt_" }).first(), 900);
await page.waitForSelector("text=Verification findings");
await click(page.locator("button", { hasText: "Approve" }), 700);
await page.waitForSelector("text=not yet marked reviewed");
await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
await caption("Approval is refused until every AI-drafted section has been reviewed", 2200);
await shot("05-approval-blocked.png");
step("blocked");

while (await page.locator("text=Mark section reviewed").count()) {
  await click(page.locator("text=Mark section reviewed").first(), 300);
}
await type(page.locator('input[placeholder="Reviewer comment"]'), "Checked against source documents");
await click(page.locator("button", { hasText: "Approve" }), 900);
await page.waitForSelector("h1 >> text=approved");
await caption("Approved, then finalised: the client copy is hashed and stored immutably", 900);
await click(page.locator("text=Finalise"), 900);
await page.waitForSelector("text=Download client copy");
await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
await page.waitForTimeout(600);
await shot("06-finalised.png", { fullPage: true });

for (const [label, file] of [
  ["Download client copy", "client.docx"],
  ["Download review copy", "review.docx"],
  ["Download evidence appendix", "evidence.docx"],
]) {
  const dl = page.waitForEvent("download");
  await click(page.locator(`text=${label}`), 300);
  await (await dl).saveAs(path.join(raw, file));
}
step("finalised");

await caption("Templates and approved wording are versioned data, approved by Compliance", 600);
await asUser("dan");
await click(page.locator("header button", { hasText: "Templates" }), 900);
await page.waitForSelector("text=Template registry");
await caption("Templates and approved wording are versioned data, approved by Compliance", 2200);
await shot("07-template-registry.png", { clip: { x: 0, y: 0, width: W, height: 380 } });
await caption("", 600);

const video = page.video();
await context.close();
await browser.close();
const videoPath = await video.path();
fs.renameSync(videoPath, path.join(raw, "walkthrough.webm"));
console.log("video:", path.join(raw, "walkthrough.webm"));
console.log("errors:", errors);
if (errors.length) process.exit(1);
