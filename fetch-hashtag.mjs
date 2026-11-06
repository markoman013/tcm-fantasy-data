// Logs in to Hashtag with the cookie secret, asks the points-projections page to score players with TCM scoring.
import fs from "fs";
const COOKIE = process.env.HASHTAG_COOKIE;
const URL = "https://hashtagbasketball.com/fantasy-basketball-points-league-projections";
const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";
const problems = [];
const meta = { fetchedAt: new Date().toISOString() };
function done(ok) { fs.mkdirSync("data", { recursive: true }); fs.writeFileSync("data/hashtag_status.json", JSON.stringify({ ok, ...meta, problems }, null, 1)); console.log(ok ? "ok" : "FAILED", problems); process.exit(0); }
if (!COOKIE) { problems.push("HASHTAG_COOKIE secret missing"); done(false); }
const hdr = { Cookie: COOKIE, "User-Agent": UA, Accept: "text/html" };
const get = await fetch(URL, { headers: hdr, redirect: "follow" });
const html = await get.text();
meta.getStatus = get.status; meta.getLen = html.length;
if (get.status !== 200) { problems.push("GET status " + get.status + (get.status === 403 ? " (blocked)" : "")); done(false); }
const form = {};
for (const m of html.matchAll(/<input[^>]*>/g)) {
  const t = m[0]; const n = /name="([^"]*)"/.exec(t)?.[1]; if (!n) continue;
  const type = /type="([^"]*)"/.exec(t)?.[1];
  if (type === "submit" || type === "button" || type === "image") continue;
  form[n] = /value="([^"]*)"/.exec(t)?.[1] ?? "";
}
for (const m of html.matchAll(/<select[^>]*name="([^"]*)"[\s\S]*?<\/select>/g)) {
  const sel = m[0]; const opt = /<option selected="selected" value="([^"]*)"/.exec(sel) || /<option value="([^"]*)"/.exec(sel);
  form[m[1]] = opt?.[1] ?? "";
}
if (!form.__VIEWSTATE) { problems.push("no form found (login/bot page?)"); fs.writeFileSync("data/hashtag_debug.html", html.slice(0, 20000)); done(false); }
const P = "ctl00$ContentPlaceHolder1$";
const scoring = { TextBox1: 1, TextBox4: 1, TextBox2: 0, TextBox3: 0, TextBox5: 2, TextBox6: 4, TextBox7: 4, TextBox14: -2, TextBox8: 1, TextBox9: 0, TextBox18: 0, TextBox10: 2, TextBox11: -1, TextBox19: 0, TextBox12: 1, TextBox13: -1, TextBox20: 0, TextBox15: 0, TextBox16: 0, TextBox17: 0, DDSHOW: "600", DDPEN: "0.00", DDBY: "0", DDDURATION: "0" };
for (const k in scoring) form[P + k] = String(scoring[k]);
form[P + "Button1"] = "UPDATE";
const FINAL = get.url || URL; meta.finalUrl = FINAL;
const post = await fetch(FINAL, { method: "POST", headers: { ...hdr, "Content-Type": "application/x-www-form-urlencoded", Referer: FINAL, Origin: "https://hashtagbasketball.com" }, body: new URLSearchParams(form) });
const ph = await post.text();
meta.postStatus = post.status; meta.postLen = ph.length;
const strip = s => s.replace(/<[^>]+>/g, "|").replace(/&nbsp;/g, " ").split("|").map(x => x.trim()).filter(Boolean);
const players = [];
for (const row of ph.match(/<tr[\s\S]*?<\/tr>/g) || []) {
  if (!row.includes('title="RANK"')) continue;
  const name = /title="NAME"[^>]*>([^<]*)</.exec(row)?.[1]?.trim();
  const pos = [...row.matchAll(/pos-pill__seg"[^>]*>([^<]*)</g)].map(x => x[1]).join(",");
  const team = /title="TEAM"[^>]*>([^<]*)</.exec(row)?.[1]?.trim();
  const nums = [...row.matchAll(/<td[^>]*>\s*(?:<span[^>]*>)?\s*(-?[\d.]+)\s*(?:<\/span>)?\s*<\/td>/g)].map(x => Number(x[1]));
  // numbers: rank, total, gp, pts, reb, ast, stl, blk, 3pm, fgm, fga, ftm, fta, to
  if (!name || nums.length < 14) continue;
  const [rank, fpts, gp, pts, reb, ast, stl, blk, tpm, fgm, fga, ftm, fta, to] = nums;
  players.push({ rank, name, pos, team, fptsPerGame: fpts, gp, pts, reb, ast, stl, blk, tpm, fgm, fga, ftm, fta, to });
}
meta.players = players.length;
if (players.length < 100) { problems.push("only " + players.length + " players parsed (not logged in or layout changed)"); fs.writeFileSync("data/hashtag_debug.html", ph.slice(0, 20000)); done(false); }
const out = { fetchedAt: meta.fetchedAt, note: "Hashtag ROS projections (updated daily), per game, scored with TCM league scoring, no injury penalty", players };
fs.writeFileSync("data/hashtag_points_projections.json", JSON.stringify(out));
const day = meta.fetchedAt.slice(0, 10);
fs.mkdirSync("data/hashtag_history", { recursive: true });
fs.writeFileSync(`data/hashtag_history/${day}.json`, JSON.stringify(out)); // latest run of the day wins
done(true);
