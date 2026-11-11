// End-to-end smoke test in a real browser (headless Chrome via playwright-core).
// Usage: BASE_URL=http://localhost:3000 DEMO_EMAIL=admin@demo.tectha.in DEMO_PASSWORD=... node e2e/smoke.mjs
// Requires the demo hospital (python -m app.cli seed-demo) and a Chrome/Chromium binary (CHROME_PATH).
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE_URL || "http://localhost:3000";
const EMAIL = process.env.DEMO_EMAIL || "admin@demo.tectha.in";
const STAFF = process.env.DEMO_STAFF_EMAIL || "staff@demo.tectha.in";
const PASSWORD = process.env.DEMO_PASSWORD;
const SLUG = process.env.DEMO_SLUG || "tectha-demo-clinic";
const OUT = process.env.SCREENSHOT_DIR || "e2e/screenshots";
const CHROME = process.env.CHROME_PATH || "/usr/bin/google-chrome";
if (!PASSWORD) throw new Error("Set DEMO_PASSWORD");
mkdirSync(OUT, { recursive: true });

const results = [];
const check = (name, ok, extra = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? "  " + extra : ""}`); };

const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });
const errors = [];
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

  // Sign in as the demo admin and reset the demo world to Monday 16 Nov 2026
  await page.goto(`${BASE}/login`);
  await page.fill("#email", EMAIL);
  await page.fill("#password", PASSWORD);
  await page.click("button[type=submit]");
  await page.waitForURL(/\/dashboard/);
  check("admin can sign in", true);
  const api = (path, body) => page.evaluate(async ([p, b]) => {
    const r = await fetch(p, { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "tectha" }, body: JSON.stringify(b ?? {}) });
    return { status: r.status, json: await r.json() };
  }, [path, body]);
  await api("/api/demo/reset", { start_monday: "2026-11-16" });
  await api("/api/demo/step", { key: "book" });

  // 1. Mr. Ravi books on the public page (mobile viewport, Tamil toggle checked too)
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
  const pub = await mobile.newPage();
  pub.on("pageerror", (e) => errors.push(e.message));
  await pub.goto(`${BASE}/book/${SLUG}`);
  await pub.getByRole("button", { name: "தமிழ்" }).click();
  check("booking page switches to Tamil", await pub.getByText("சந்திப்பை முன்பதிவு செய்யுங்கள்").isVisible());
  await pub.screenshot({ path: `${OUT}/booking-ta-mobile.png`, fullPage: true });
  await pub.getByRole("button", { name: "English" }).click();
  await pub.getByRole("button", { name: /Dr\. Meena Sundaram/ }).click();
  await pub.getByRole("button", { name: /Wed\s*18\s*Nov/ }).click();
  await pub.getByRole("button", { name: "10:30 AM" }).click();
  await pub.fill("#name", "Mr. Ravi");
  await pub.fill("#phone", "98765 43210");
  await pub.screenshot({ path: `${OUT}/booking-en-mobile.png`, fullPage: true });
  await pub.getByRole("button", { name: "Book appointment" }).click();
  await pub.getByText("You're booked").waitFor();
  const ref = await pub.locator("p.num.text-3xl").innerText();
  check("public booking shows a reference", /^TT-[A-Z0-9]{6}$/.test(ref), ref);
  await pub.screenshot({ path: `${OUT}/booking-confirmed-mobile.png`, fullPage: true });

  // Same slot again must be refused
  await pub.getByRole("button", { name: "Book another appointment" }).click();
  await pub.getByRole("button", { name: /Dr\. Meena Sundaram/ }).click();
  await pub.getByRole("button", { name: /Wed\s*18\s*Nov/ }).click();
  const taken = pub.getByRole("button", { name: "10:30 AM" });
  check("booked slot is shown as taken", await taken.isDisabled());

  // 2–3. Reminder goes out; Ravi taps Confirm in the demo WhatsApp thread
  await api("/api/demo/step", { key: "reminder" });
  await page.goto(`${BASE}/demo`);
  await page.getByText("Ravi's WhatsApp").waitFor();
  await page.getByRole("button", { name: "Confirm", exact: true }).first().click();
  await page.getByText(/Thank you, Mr\. Ravi/).waitFor();
  check("Confirm tap produces the confirmation reply", true);
  await page.screenshot({ path: `${OUT}/demo-controls.png`, fullPage: true });

  // 4. Staff marks the visit done and schedules the follow-up through the UI
  await api("/api/demo/clock", { local_datetime: "2026-11-18T10:45:00" });
  await page.goto(`${BASE}/appointments?date=2026-11-18`);
  await page.getByRole("link", { name: "Mr. Ravi" }).click();
  await page.waitForURL(/\/appointments\//);
  await page.getByRole("button", { name: "Visited" }).first().click();
  await page.getByText("Marked as visited").waitFor();
  await page.getByRole("button", { name: "2 weeks" }).click();
  check("2 weeks from 18 Nov suggests 2 Dec", (await page.locator("input[type=date]").inputValue()) === "2026-12-02");
  check("form previews reminder dates 25 & 29 Nov", await page.getByText(/Reminders on .*25 Nov.* and .*29 Nov/).isVisible());
  await page.getByRole("button", { name: "Schedule follow-up" }).click();
  await page.getByText("Follow-up scheduled").waitFor();
  await page.screenshot({ path: `${OUT}/appointment-detail.png`, fullPage: true });

  // 5–7. Reminders on 25 and 29 Nov; no reply → red on 30 Nov for reception staff
  for (const key of ["reminder_7d", "reminder_3d", "red"]) await api("/api/demo/step", { key });
  await page.getByRole("button", { name: "Sign out" }).first().click().catch(() => {});
  await page.goto(`${BASE}/login`);
  await page.fill("#email", STAFF);
  await page.fill("#password", PASSWORD);
  await page.click("button[type=submit]");
  await page.waitForURL(/\/dashboard/);
  const callList = page.locator("section", { has: page.getByRole("heading", { name: "Call these patients" }) });
  await callList.getByText("Mr. Ravi").waitFor();
  check("Ravi is red on the staff dashboard", await callList.locator("li", { hasText: "Mr. Ravi" }).getByText("No reply to reminders").isVisible());
  await page.screenshot({ path: `${OUT}/dashboard-staff.png`, fullPage: true });
  check("staff cannot see the monthly report in navigation", !(await page.getByRole("link", { name: "Monthly report" }).isVisible()));

  // Admin screens
  await page.goto(`${BASE}/login`);
  await api("/api/auth/logout");
  await page.goto(`${BASE}/login`);
  await page.fill("#email", EMAIL);
  await page.fill("#password", PASSWORD);
  await page.click("button[type=submit]");
  await page.waitForURL(/\/dashboard/);
  await page.getByText(/We brought back/).first().waitFor();
  await page.screenshot({ path: `${OUT}/dashboard-admin.png`, fullPage: true });
  for (const [path, name, text] of [
    ["/follow-ups", "follow-ups", "Needs a call"], ["/patients", "patients", "Mr. Ravi"], ["/reports", "reports", "this month."],
    ["/settings", "settings", "Booking link"], ["/staff", "staff", "Reception Desk"], ["/whatsapp", "whatsapp", "Setup checklist"],
    ["/templates", "templates", "Appointment reminder"], ["/messages", "messages", "Scheduled"],
  ]) {
    await page.goto(`${BASE}${path}`);
    await page.getByText(text).first().waitFor({ timeout: 10000 });
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
    check(`${path} renders`, true);
  }
  const reportText = await page.goto(`${BASE}/reports`).then(() => page.getByText(/We brought back/).first().innerText());
  check("report headline present", /We brought back \d+ patients? this month\./.test(reportText.replace(/\s+/g, " ")), reportText.replace(/\s+/g, " "));
  await page.goto(`${BASE}/templates`);
  await page.getByRole("button", { name: /தமிழ் Tamil/ }).first().click();
  await page.screenshot({ path: `${OUT}/templates-tamil.png`, fullPage: true });

  const mob = await mobile.newPage();
  await mob.goto(`${BASE}/login`);
  await mob.fill("#email", STAFF);
  await mob.fill("#password", PASSWORD);
  await mob.click("button[type=submit]");
  await mob.waitForURL(/\/dashboard/);
  await mob.getByText("Call these patients").waitFor();
  await mob.screenshot({ path: `${OUT}/dashboard-mobile.png`, fullPage: true });
  const overflow = await mob.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  check("mobile dashboard has no horizontal overflow", !overflow);
} catch (e) {
  check("unexpected error", false, e.message.split("\n")[0]);
} finally {
  await browser.close();
}
const relevant = errors.filter((e) => !/Failed to load resource: the server responded with a status of (401|404|409)/.test(e));
check("no browser console errors", relevant.length === 0, relevant.slice(0, 3).join(" | "));
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
