// Makes a move on ESPN for team 9 (TCM). Inputs come from environment variables set by the workflow.
import { mkdirSync, writeFileSync } from "node:fs";

const LEAGUE = "1838678745", TEAM = 9;
const BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/2027";
const L = `${BASE}/segments/0/leagues/${LEAGUE}`;
const WRITE = `https://lm-api-writes.fantasy.espn.com/apis/v3/games/fba/seasons/2027/segments/0/leagues/${LEAGUE}/transactions/`;
const swid = process.env.SWID;
const headers = { Cookie: `espn_s2=${process.env.ESPN_S2}; SWID=${swid}`, "User-Agent": "Mozilla/5.0", Accept: "application/json",
  Origin: "https://fantasy.espn.com", Referer: `https://fantasy.espn.com/basketball/team?leagueId=${LEAGUE}&teamId=${TEAM}` };
const E = process.env;
const DRY = (E.TEST_RUN || "Yes") !== "No";
const log = [];
const say = (m) => { console.log(m); log.push(`${new Date().toISOString()} ${m}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function finish(result) {
  mkdirSync("data", { recursive: true });
  writeFileSync("data/move_log.json", JSON.stringify({ result, dryRun: DRY, inputs: { mode: E.MODE, add: E.ADD, drop: E.DROP, afterTipTeam: E.AFTER_TIP_TEAM, ifOut: E.IF_OUT, starter: E.STARTER, replacement: E.REPLACEMENT, onlyIfOut: E.ONLY_IF_OUT, swapBack: E.SWAP_BACK }, log }, null, 1));
  console.log("RESULT:", result);
  process.exit(0);
}
async function get(url, extra = {}) {
  const r = await fetch(url, { headers: { ...headers, ...extra } });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}
async function post(body) {
  const r = await fetch(WRITE, { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const t = await r.text();
  return { ok: r.ok, status: r.status, text: t.slice(0, 400) };
}
const readTeam = async () => {
  const j = await get(`${L}?view=mRoster&view=mTeam&view=mSettings`);
  const t = j.teams.find((x) => x.id === TEAM);
  const roster = t.roster.entries.map((e) => ({ id: e.playerPoolEntry.player.id, name: e.playerPoolEntry.player.fullName, slot: e.lineupSlotId,
    inj: e.playerPoolEntry.player.injuryStatus, proTeam: e.playerPoolEntry.player.proTeamId, elig: e.playerPoolEntry.player.eligibleSlots }));
  return { period: j.scoringPeriodId, roster, irSlots: j.settings.rosterSettings.lineupSlotCounts["13"] };
};
const findOnRoster = (roster, name) => roster.filter((p) => p.name.toLowerCase().includes(name.toLowerCase()));
async function findFreeAgent(name, period) {
  const f = { players: { filterName: { value: name }, sortPercOwned: { sortPriority: 1, sortAsc: false }, limit: 10 } };
  const j = await get(`${L}?view=kona_player_info&scoringPeriodId=${period}`, { "x-fantasy-filter": JSON.stringify(f) });
  return (j.players || []).filter((p) => p.player.fullName.toLowerCase().includes(name.toLowerCase()))
    .map((p) => ({ id: p.id, name: p.player.fullName, status: p.status, onTeamId: p.onTeamId }));
}
const sameLineup = (a, b) => JSON.stringify(a.map((p) => [p.id, p.slot]).sort()) === JSON.stringify(b.map((p) => [p.id, p.slot]).sort());

try {
  if (!E.ESPN_S2 || !E.SWID) await finish("STOPPED: ESPN login secrets are missing");

  // ---------- swap two players' lineup slots (plain, or only if the starter is really OUT) ----------
  if (E.MODE === "swap") {
    const s0 = await readTeam();
    const a = findOnRoster(s0.roster, E.STARTER), b = findOnRoster(s0.roster, E.REPLACEMENT);
    if (a.length !== 1 || b.length !== 1) await finish(`STOPPED: need exactly one roster match each for "${E.STARTER}" (found ${a.length}) and "${E.REPLACEMENT}" (found ${b.length})`);
    let [pa, pb] = [a[0], b[0]];
    const mk = (x, y, period) => ({ isLeagueManager: false, teamId: TEAM, type: "ROSTER", memberId: swid, scoringPeriodId: period, executionType: "EXECUTE",
      items: [{ playerId: x.id, type: "LINEUP", fromLineupSlotId: x.slot, toLineupSlotId: y.slot }, { playerId: y.id, type: "LINEUP", fromLineupSlotId: y.slot, toLineupSlotId: x.slot }] });
    const eligible = (p, slot) => p.elig.includes(slot);
    const doSwap = async (x, y, period) => { // x and y hold their CURRENT slots
      if (!eligible(x, y.slot) || !eligible(y, x.slot)) { say(`Not eligible: ${x.name} slot ${x.slot} / ${y.name} slot ${y.slot}`); return false; }
      const r = await post(mk(x, y, period)); say(`swap ${x.name} <-> ${y.name} -> ${r.status} ${r.ok ? "" : r.text.slice(0, 160)}`);
      if (!r.ok) return false;
      await sleep(2500);
      const c = await readTeam();
      const ok = c.roster.find((p) => p.id === x.id).slot === y.slot && c.roster.find((p) => p.id === y.id).slot === x.slot;
      say(`verified: ${ok}`);
      return ok;
    };
    say(`Before: ${pa.name} slot ${pa.slot} (${pa.inj}), ${pb.name} slot ${pb.slot} (${pb.inj}), period ${s0.period}`);

    if ((E.ONLY_IF_OUT || "No") !== "Yes") {
      // plain swap, optionally swap back right away (for testing)
      if (DRY) await finish(`TEST RUN: would swap ${pa.name} (slot ${pa.slot}) and ${pb.name} (slot ${pb.slot})${E.SWAP_BACK === "Yes" ? " and swap back" : ""}`);
      if (!(await doSwap(pa, pb, s0.period))) await finish("FAILED: swap did not happen, check ESPN");
      if (E.SWAP_BACK === "Yes") {
        const c = await readTeam();
        const x = c.roster.find((p) => p.id === pa.id), y = c.roster.find((p) => p.id === pb.id);
        const back = await doSwap(x, y, c.period);
        await sleep(1000);
        const fin = await readTeam();
        await finish(back && sameLineup(s0.roster, fin.roster) ? "OK: swapped and swapped back, lineup restored" : "CHECK NEEDED: swap back may not have worked");
      }
      await finish(`OK: swapped ${pa.name} and ${pb.name}`);
    }

    // conditional swap: starter must be really OUT; checked again right before tip-off, swaps back if not
    const sch = await get(`${BASE}?view=proTeamSchedules_wl`);
    const tipOf = (proTeamId) => { const t = sch.settings.proTeams.find((x) => x.id === proTeamId); const g = (t && t.proGamesByScoringPeriod[String(s0.period)]) || []; return g.length ? new Date(g[0].date).getTime() : null; };
    const tipA = tipOf(pa.proTeam), tipB = tipOf(pb.proTeam);
    if (!tipA) await finish(`STOPPED: ${pa.name}'s team has no game in scoring period ${s0.period}`);
    if (!tipB) await finish(`STOPPED: ${pb.name}'s team has no game in scoring period ${s0.period}, swapping him in would not help`);
    if (Date.now() > Math.min(tipA, tipB) - 120000) await finish("STOPPED: a tip-off is too close or has passed, no changes made");
    say(`${pa.name} tips ${new Date(tipA).toISOString()}, ${pb.name} tips ${new Date(tipB).toISOString()}`);
    if (DRY) await finish(`TEST RUN: would watch ${pa.name} until 4 minutes before tip-off. Swaps with ${pb.name} only if OUT on two checks 5 minutes apart (or OUT at the final check), swaps back if he stops being OUT. Right now ${pa.name} is ${pa.inj}`);
    const deadline = Math.min(tipA, tipB) - 4 * 60000;
    if (deadline - Date.now() > 330 * 60000) await finish("STOPPED: tip-off is more than 5.5 hours away, start this closer to the game");
    let swapped = false, outStreak = 0, cur = { a: pa, b: pb };
    while (true) {
      const c = await readTeam();
      const x = c.roster.find((p) => p.id === pa.id), y = c.roster.find((p) => p.id === pb.id);
      if (!x || !y) await finish("STOPPED: a player is no longer on the roster, no more changes");
      const isOut = x.inj === "OUT";
      outStreak = isOut ? outStreak + 1 : 0;
      const finalCheck = Date.now() >= deadline - 30000;
      say(`${x.name} is ${x.inj} (out streak ${outStreak})${finalCheck ? " [final check]" : ""}`);
      if (!swapped && isOut && (outStreak >= 2 || finalCheck)) {
        swapped = await doSwap(x, y, c.period);
        if (!swapped) await finish("FAILED: tried to swap, it did not work, check ESPN");
      } else if (swapped && !isOut) {
        const back = await doSwap(y, x, c.period); // after our swap, y holds the starter slot
        if (!back) await finish("FAILED: tried to put him back, it did not work, check ESPN NOW");
        swapped = false;
      }
      if (finalCheck) await finish(swapped ? `DONE: ${pa.name} is OUT, ${pb.name} is starting in his slot` : `DONE: ${pa.name} is not OUT, lineup unchanged`);
      await sleep(Math.min(300000, Math.max(5000, deadline - 20000 - Date.now())));
    }
  }

  // ---------- add / drop with optional wait for tip-off and optional IR rule ----------
  if (E.MODE === "add_drop") {
    let s = await readTeam();
    if (E.AFTER_TIP_TEAM && !E.AFTER_TIP_TEAM.toLowerCase().startsWith("none")) {
      const sch = await get(`${BASE}?view=proTeamSchedules_wl`);
      const want = E.AFTER_TIP_TEAM.toLowerCase();
      const team = sch.settings.proTeams.find((t) => t.id > 0 && want.includes(String(t.name).toLowerCase())) || sch.settings.proTeams.find((t) => t.abbrev.toLowerCase() === want);
      if (!team) await finish(`STOPPED: team "${E.AFTER_TIP_TEAM}" not found`);
      const games = team.proGamesByScoringPeriod[String(s.period)] || [];
      if (!games.length) await finish(`STOPPED: ${team.abbrev} has no game in scoring period ${s.period}`);
      const tip = new Date(games[0].date).getTime();
      say(`${team.abbrev} tip-off ${new Date(tip).toISOString()}`);
      if (tip - Date.now() > 330 * 60000) await finish("STOPPED: tip-off is more than 5.5 hours away, start this closer to the game");
      while (Date.now() < tip + 90000) await sleep(15000);
      say("tip-off passed, waited 90 s");
      s = await readTeam();
    }
    const drops = E.DROP ? findOnRoster(s.roster, E.DROP) : [];
    if (E.DROP && drops.length !== 1) await finish(`STOPPED: expected exactly one roster match for drop "${E.DROP}", found ${drops.length}`);
    const fas = await findFreeAgent(E.ADD, s.period);
    if (fas.length !== 1 || fas[0].status !== "FREEAGENT") await finish(`STOPPED: add target "${E.ADD}" is not a single FREEAGENT: ${JSON.stringify(fas)}`);
    const add = fas[0];
    let useDrop = drops[0] || null;
    // IR rule: if IF_OUT player is OUT and an IR slot is open, move him to IR and skip the drop
    if (E.IF_OUT) {
      const o = findOnRoster(s.roster, E.IF_OUT);
      if (o.length !== 1) await finish(`STOPPED: expected one roster match for IF_OUT "${E.IF_OUT}"`);
      const irUsed = s.roster.filter((p) => p.slot === 13).length;
      say(`${o[0].name} status ${o[0].inj}, IR slots used ${irUsed}/${s.irSlots}`);
      if (o[0].inj === "OUT" && o[0].slot !== 13 && irUsed < s.irSlots) {
        say(`Case A: moving ${o[0].name} to IR`);
        if (DRY) await finish(`TEST RUN: would move ${o[0].name} to IR then add ${add.name} without dropping anyone`);
        const r = await post({ isLeagueManager: false, teamId: TEAM, type: "ROSTER", memberId: swid, scoringPeriodId: s.period, executionType: "EXECUTE",
          items: [{ playerId: o[0].id, type: "LINEUP", fromLineupSlotId: o[0].slot, toLineupSlotId: 13 }] });
        say(`IR move -> ${r.status} ${r.text.slice(0, 160)}`);
        await sleep(2500);
        const chk = await readTeam();
        if (!r.ok || chk.roster.find((p) => p.id === o[0].id).slot !== 13) { say("IR move did not happen, falling back to add/drop (Case B)"); }
        else useDrop = null;
      } else say("Case B/C: not moving anyone to IR");
    }
    const items = [{ playerId: add.id, type: "ADD", toTeamId: TEAM }];
    if (useDrop) items.push({ playerId: useDrop.id, type: "DROP", fromTeamId: TEAM });
    if (DRY) await finish(`TEST RUN: would add ${add.name}${useDrop ? ` and drop ${useDrop.name}` : " with no drop"}`);
    const r = await post({ isLeagueManager: false, teamId: TEAM, type: "FREEAGENT", scoringPeriodId: s.period, executionType: "EXECUTE", items });
    say(`add/drop -> ${r.status} ${r.text.slice(0, 300)}`);
    await sleep(3000);
    const after = await readTeam();
    const hasAdd = after.roster.some((p) => p.id === add.id);
    const hasDrop = useDrop ? after.roster.some((p) => p.id === useDrop.id) : false;
    await finish(r.ok && hasAdd ? `OK: ${add.name} added${useDrop ? (hasDrop ? `, ${useDrop.name} drop is pending (still on roster until the lock lifts)` : `, ${useDrop.name} dropped`) : ""}` : `FAILED or pending: http ${r.status}, ${add.name} on roster: ${hasAdd}. Check ESPN.`);
  }
  await finish(`STOPPED: unknown MODE "${E.MODE}"`);
} catch (e) { say(`ERROR ${e.message}`); await finish(`ERROR: ${e.message}`); }
