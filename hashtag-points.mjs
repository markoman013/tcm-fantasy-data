// Turns Hashtag's public per-game stat tables into fantasy points per game using TCM league scoring.
import fs from "fs";
const strip = s => s.replace(/<[^>]+>/g, "|").replace(/&nbsp;/g," ").split("|").map(x => x.trim()).filter(Boolean);
function parse(file) {
  if (!fs.existsSync(file)) return [];
  const html = fs.readFileSync(file, "utf8");
  const out = [];
  for (const row of html.match(/<tr[\s\S]*?<\/tr>/g) || []) {
    const c = strip(row);
    // expected: rank, name, short, pos, team, gp, mpg, fg%, (m/a), ft%, (m/a), 3pm, pts, reb, ast, stl, blk, to, total
    const i = c.findIndex(x => /^\(\d/.test(x));
    if (i < 0) continue;
    const pm = x => (x.match(/\(([\d.]+)\/([\d.]+)\)/) || []).slice(1).map(Number);
    const [fgm, fga] = pm(c[i]);
    const j = c.findIndex((x, k) => k > i && /^\(\d/.test(x));
    const [ftm, fta] = pm(c[j]);
    const n = c.slice(j + 1).map(Number);
    if ([fgm, fga, ftm, fta].some(v => !isFinite(v)) || n.length < 7) continue;
    const [tpm, pts, reb, ast, stl, blk, to] = n;
    const fp = 2*fgm - fga + ftm - fta + tpm + reb + 2*ast + 4*stl + 4*blk - 2*to + pts;
    out.push({ rank: Number(c[0]), name: c[1], pos: c[i-5] || "", gp: Number(c[i-3]), mpg: Number(c[i-2]),
      fgm, fga, ftm, fta, tpm, pts, reb, ast, stl, blk, to, hashtagCatTotal: n[7] ?? null, fptsPerGame: Math.round(fp*100)/100 });
  }
  return out;
}
const rows = [...parse("data/hashtag_rankings.html"), ...parse("data/hashtag_projections.html")];
const seen = new Map(); rows.forEach(r => { if (!seen.has(r.name)) seen.set(r.name, r); });
const list = [...seen.values()].sort((a,b)=>b.fptsPerGame-a.fptsPerGame);
fs.writeFileSync("data/hashtag_fpts.json", JSON.stringify({ computedAt: new Date().toISOString(), scoring: "FGM2 FGA-1 FTM1 FTA-1 3PM1 REB1 AST2 STL4 BLK4 TO-2 PTS1", players: list }, null, 1));
console.log("players:", list.length, list.slice(0,5).map(p=>p.name+" "+p.fptsPerGame).join(", "));
