// Pulls everything the TCM Hub updates need and saves it as JSON in ./data
import { mkdirSync, writeFileSync, existsSync } from "node:fs";

const LEAGUE = "1838678745";
const BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/2027";
const L = `${BASE}/segments/0/leagues/${LEAGUE}`;
const headers = {
  Cookie: `espn_s2=${process.env.ESPN_S2}; SWID=${process.env.SWID}`,
  "User-Agent": "Mozilla/5.0",
  Accept: "application/json",
};

async function get(url, extra = {}) {
  const res = await fetch(url, { headers: { ...headers, ...extra } });
  if (!res.ok) throw new Error(`${res.status} for ${url}`);
  return res.json();
}
mkdirSync("data/boxscores", { recursive: true });
const save = (name, obj) => writeFileSync(`data/${name}.json`, JSON.stringify(obj));
const problems = [];
async function safe(label, fn) {
  try { await fn(); } catch (e) { problems.push(`${label}: ${e.message}`); console.log("PROBLEM", label, e.message); }
}

// 1. League: all 10 rosters with player stats (season, last 7/15/30, ESPN projections), teams, standings,
//    matchup schedule and scores, league settings, add counts and limits.
let league;
await safe("league", async () => {
  league = await get(`${L}?view=mTeam&view=mRoster&view=kona_playercard&view=mMatchupScore&view=mSettings&view=mStandings&view=mPendingTransactions`);
  save("league", league);
});
if (!league) { console.error("League fetch failed, stopping."); process.exit(1); }
const period = league.scoringPeriodId;

// 2. Day by day box scores: one file per scoring period (period 1 = Oct 20, 2026).
//    Past days never change, so they are only fetched once. The last two days are always refreshed.
for (let p = 1; p <= period; p++) {
  const file = `data/boxscores/${p}.json`;
  if (existsSync(file) && p < period - 1) continue;
  await safe(`boxscore ${p}`, async () => {
    save(`boxscores/${p}`, await get(`${L}?view=mBoxscore&view=mMatchupScore&scoringPeriodId=${p}`));
  });
}


// 2b. Lineups as set for today AND tomorrow (ESPN keeps a separate lineup per day, so tomorrow's can differ from today's)
await safe("lineups", async () => {
  const out = { fetchedAt: new Date().toISOString(), periods: {} };
  for (const p of [period, period + 1]) {
    const j = await get(`${L}?view=mRoster&scoringPeriodId=${p}`);
    out.periods[p] = Object.fromEntries(j.teams.map((t) => [t.id, t.roster.entries.map((e) => ({ id: e.playerPoolEntry.player.id, name: e.playerPoolEntry.player.fullName, slot: e.lineupSlotId, inj: e.playerPoolEntry.player.injuryStatus, proTeam: e.playerPoolEntry.player.proTeamId }))]));
  }
  save("lineups", out);
});

// 3. NBA schedule for every team, all season
await safe("schedules", async () => save("schedules", await get(`${BASE}?view=proTeamSchedules_wl`)));

// 4. Free agents and players on waivers (with stats and projections), top 500 by ownership
await safe("freeagents", async () => {
  const filter = { players: { filterStatus: { value: ["FREEAGENT", "WAIVERS"] }, limit: 500, sortPercOwned: { sortPriority: 1, sortAsc: false } } };
  save("freeagents", await get(`${L}?view=kona_player_info&scoringPeriodId=${period}`, { "x-fantasy-filter": JSON.stringify(filter) }));
});

// 5. Recent transactions (adds, drops, trades) in the league
await safe("transactions", async () => save("transactions", await get(`${L}?view=mTransactions2`)));

// 6. Hashtag Basketball public pages (best effort, may be blocked or partly hidden behind login)
const hb = { "hashtag_defense_vs_position": "https://hashtagbasketball.com/nba-defense-vs-position",
  "hashtag_projections": "https://hashtagbasketball.com/fantasy-basketball-projections",
  "hashtag_rankings": "https://hashtagbasketball.com/fantasy-basketball-rankings" };
const probe = {};
for (const [name, url] of Object.entries(hb)) {
  await safe(`hashtag ${name}`, async () => {
    const res = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0", Accept: "text/html" } });
    const text = await res.text();
    probe[name] = { status: res.status, bytes: text.length, rows: (text.match(/<tr/g) || []).length, mentionsPremium: /premium|subscribe|log in|login/i.test(text) };
    if (res.ok) writeFileSync(`data/${name}.html`, text); else throw new Error(String(res.status));
  });
}
save("hashtag_probe", probe);

save("meta", { fetchedAt: new Date().toISOString(), scoringPeriodId: period, problems });
console.log("saved, scoring period", period, "problems:", problems.length);
