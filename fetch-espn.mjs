// Pulls TCM league data from ESPN and saves JSON files in ./data
import { mkdirSync, writeFileSync } from "node:fs";

const LEAGUE = "1838678745";
const BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/2027";
const cookie = `espn_s2=${process.env.ESPN_S2}; SWID=${process.env.SWID}`;
const headers = { Cookie: cookie, "User-Agent": "Mozilla/5.0", Accept: "application/json" };

async function get(url, extra = {}) {
  const res = await fetch(url, { headers: { ...headers, ...extra } });
  if (!res.ok) throw new Error(`${res.status} for ${url}`);
  return res.json();
}

mkdirSync("data", { recursive: true });
const save = (name, obj) => writeFileSync(`data/${name}.json`, JSON.stringify(obj));
const L = `${BASE}/segments/0/leagues/${LEAGUE}`;

const league = await get(`${L}?view=mTeam&view=mRoster&view=mMatchupScore&view=mSettings&view=mStandings`);
save("league", league);

const period = league.scoringPeriodId;
save("boxscore", await get(`${L}?view=mBoxscore&view=mMatchupScore&scoringPeriodId=${period}`));
save("schedules", await get(`${BASE}?view=proTeamSchedules_wl`));

const filter = {
  players: {
    filterStatus: { value: ["FREEAGENT", "WAIVERS"] },
    limit: 300,
    sortPercOwned: { sortPriority: 1, sortAsc: false },
  },
};
save("freeagents", await get(`${L}?view=kona_player_info&scoringPeriodId=${period}`, {
  "x-fantasy-filter": JSON.stringify(filter),
}));

save("meta", { fetchedAt: new Date().toISOString(), scoringPeriodId: period });
console.log("saved, scoring period", period);
