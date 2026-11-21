// Raindrop.io -> summarized Markdown notes with screenshots.
// Runs in GitHub Actions; commits results back to the repo.
import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const RAINDROP_TOKEN = process.env.RAINDROP_TOKEN;
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const GEMINI_MODEL = process.env.GEMINI_MODEL || "gemini-3.8-flash";
// USD per 1M tokens (gemini-3.8-flash paid tier: $0.75/$3.75 through 2026-12-31, $1.50/$7.50 from 2027-01-01).
const intro = new Date() < new Date("2027-01-01T00:00:00Z");
const PRICE_IN = Number(process.env.GEMINI_PRICE_IN || (intro ? 0.75 : 1.5));
const PRICE_OUT = Number(process.env.GEMINI_PRICE_OUT || (intro ? 3.75 : 7.5));
const usageRows = [];
const LOOKBACK_HOURS = Number(process.env.INITIAL_LOOKBACK_HOURS || 24);
const MAX_PER_RUN = Number(process.env.MAX_PER_RUN || 25);
const STATE_FILE = "state.json";

if (!RAINDROP_TOKEN) throw new Error("RAINDROP_TOKEN secret is missing");

async function readState() {
  try {
    return JSON.parse(await fs.readFile(STATE_FILE, "utf8"));
  } catch {
    return { lastCreated: new Date(Date.now() - LOOKBACK_HOURS * 3600e3).toISOString(), seen: [] };
  }
}

async function fetchNewBookmarks(since) {
  const out = [];
  for (let page = 0; page < 5; page++) {
    const url = `https://api.raindrop.io/rest/v1/raindrops/0?sort=-created&perpage=50&page=${page}`;
    const res = await fetch(url, { headers: { Authorization: `Bearer ${RAINDROP_TOKEN}` } });
    if (!res.ok) throw new Error(`Raindrop API ${res.status}: ${await res.text()}`);
    const { items = [] } = await res.json();
    const fresh = items.filter((i) => i.created > since);
    out.push(...fresh);
    if (fresh.length < items.length || items.length < 50) break;
  }
  return out.reverse(); // oldest first
}

async function summarize(b) {
  if (!GEMINI_API_KEY) return "";
  const prompt =
    `Summarize this bookmarked web page in 3-5 sentences of plain prose.\n\n` +
    `Title: ${b.title || ""}\nURL: ${b.link || ""}\nExcerpt: ${b.excerpt || "(none)"}`;
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY },
      body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] }),
    }
  );
  if (!res.ok) {
    console.warn(`Gemini ${res.status}: ${await res.text()}`);
    return "";
  }
  const data = await res.json();
  const u = data?.usageMetadata || {};
  const inTok = u.promptTokenCount || 0;
  const outTok = u.candidatesTokenCount || 0;
  const thinkTok = u.thoughtsTokenCount || 0;
  const cost = (inTok * PRICE_IN + (outTok + thinkTok) * PRICE_OUT) / 1e6;
  usageRows.push({ title: b.title || b.link, inTok, outTok, thinkTok, cost });
  console.log(`Gemini usage for ${b._id}: in=${inTok} out=${outTok} thinking=${thinkTok} cost=$${cost.toFixed(5)} (paid-tier rate)`);
  return data?.candidates?.[0]?.content?.parts?.map((p) => p.text).join("").trim() || "";
}

async function screenshot(browser, link, file) {
  if (!link || !/^https?:\/\//.test(link)) return false;
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.goto(link, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(2500);
    await page.screenshot({ path: file, type: "jpeg", quality: 70 });
    return true;
  } catch (e) {
    console.warn(`Screenshot failed for ${link}: ${e.message}`);
    return false;
  } finally {
    await page.close();
  }
}

const slug = (s) =>
  (s || "untitled").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "untitled";
const yamlStr = (s) => JSON.stringify(s ?? "");

async function main() {
  const state = await readState();
  const seen = new Set(state.seen || []);
  const bookmarks = (await fetchNewBookmarks(state.lastCreated)).filter((b) => !seen.has(b._id)).slice(0, MAX_PER_RUN);
  console.log(`New bookmarks: ${bookmarks.length}`);
  if (!bookmarks.length) return;

  const browser = await chromium.launch();
  try {
    for (const b of bookmarks) {
      const d = new Date(b.created);
      const dir = path.join("notes", String(d.getUTCFullYear()), String(d.getUTCMonth() + 1).padStart(2, "0"));
      await fs.mkdir(dir, { recursive: true });
      await fs.mkdir("screenshots", { recursive: true });

      const shotRel = `screenshots/${b._id}.jpg`;
      const hasShot = await screenshot(browser, b.link, shotRel);
      const summary = await summarize(b);
      const tags = (b.tags || []).map((t) => yamlStr(t)).join(", ");
      const shotLink = path.relative(dir, shotRel).split(path.sep).join("/");

      const md = [
        "---",
        `title: ${yamlStr(b.title)}`,
        `url: ${yamlStr(b.link)}`,
        `domain: ${yamlStr(b.domain)}`,
        `raindrop_id: ${b._id}`,
        `created: ${b.created}`,
        `tags: [${tags}]`,
        "---",
        "",
        `# ${b.title || b.link}`,
        "",
        `[${b.link}](${b.link})`,
        "",
        hasShot ? `![Screenshot](${shotLink})\n` : "",
        "## Summary",
        "",
        summary || b.excerpt || "_No summary available._",
        "",
        b.excerpt ? `## Excerpt\n\n> ${b.excerpt.replace(/\n/g, "\n> ")}\n` : "",
        b.note ? `## Note\n\n${b.note}\n` : "",
      ].join("\n");

      await fs.writeFile(path.join(dir, `${slug(b.title)}-${b._id}.md`), md);
      seen.add(b._id);
      if (b.created > state.lastCreated) state.lastCreated = b.created;
      console.log(`Saved ${b._id}: ${b.title}`);
    }
  } finally {
    await browser.close();
  }
  await writeUsageSummary();
  state.seen = [...seen].slice(-500);
  await fs.writeFile(STATE_FILE, JSON.stringify(state, null, 2) + "\n");
}

async function writeUsageSummary() {
  if (!usageRows.length) return;
  const total = usageRows.reduce((a, r) => a + r.cost, 0);
  console.log(`Gemini total this run: $${total.toFixed(5)} for ${usageRows.length} bookmark(s)`);
  if (!process.env.GITHUB_STEP_SUMMARY) return;
  const lines = [
    `### Gemini usage (${GEMINI_MODEL}, $${PRICE_IN}/$${PRICE_OUT} per 1M in/out)`,
    "",
    "| Bookmark | Input | Output | Thinking | Cost |",
    "| --- | ---: | ---: | ---: | ---: |",
    ...usageRows.map((r) => `| ${String(r.title).replace(/\|/g, "/")} | ${r.inTok} | ${r.outTok} | ${r.thinkTok} | $${r.cost.toFixed(5)} |`),
    `| **Total** | | | | **$${total.toFixed(5)}** |`,
    "",
    "_Cost shown at paid-tier rates; it's $0 if the key is on the free tier._",
    "",
  ];
  await fs.appendFile(process.env.GITHUB_STEP_SUMMARY, lines.join("\n"));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
