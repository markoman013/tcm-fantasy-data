#!/usr/bin/env python3
"""Builds the Weekly Matchups data for the TCM hub from the repo's data/ files.
No AI involved: everything is computed from ESPN + Hashtag data pulled by the loop.
Writes data/hub_state.json (full MATCHUPS list), data/hub_matchups.js (the 3 JS vars the page needs)
and data/hub_meta.json (alert / data age / one-paragraph summary for the daily message).
Usage: python3 build_hub.py          (uses the current time)
       NOW=2026-11-11T06:00:00Z python3 build_hub.py   (test with another time)
"""
import json, os, re, math, datetime as dt, functools
from zoneinfo import ZoneInfo

D = 'data/'
ME = 9
ET = ZoneInfo('America/New_York')
CET = ZoneInfo('Europe/Madrid')
BASE = dt.date(2026, 10, 20)          # scoring period 1 (US Eastern date)
SEASON_END = dt.date(2027, 3, 28)
ADDS_PER_DAY = 5 / 7
HUBABBR = {'GS': 'GSW', 'NO': 'NOP', 'NY': 'NYK', 'SA': 'SAS', 'UTAH': 'UTA', 'WSH': 'WAS'}
SLOTS = [0, 1, 2, 3, 4, 5, 6, 11, 11, 11]
POS = {0: 'PG', 1: 'SG', 2: 'SF', 3: 'PF', 4: 'C'}
SOURCES = ['Claude', 'Hashtag Basketball', 'ESPN', 'LineupExperts']
NAME_OVERRIDE = {'Amen Thompson': 'A. Thompson', 'Klay Thompson': 'K. Thompson', 'Brandon Miller': 'B. Miller',
                 'Davion Mitchell': 'D. Mitchell', 'Wendell Carter Jr.': 'Carter Jr.', 'Trey Murphy III': 'Murphy',
                 "Ja'Kobe Walter": 'Walter', 'Darius Acuff Jr.': 'Acuff'}


def load(p, default=None):
    try:
        with open(D + p) as f:
            return json.load(f)
    except Exception:
        return default


def norm(n):
    n = re.sub(r"[.'’]", '', n.lower())
    n = re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', n)
    return re.sub(r'\s+', ' ', n).strip()


now = dt.datetime.fromisoformat(os.environ['NOW'].replace('Z', '+00:00')) if os.environ.get('NOW') else dt.datetime.now(dt.timezone.utc)
L = load('league.json')
META = load('meta.json', {})
SCH = load('schedules.json')
HT = load('hashtag_points_projections.json', {'players': []})
HTS = load('hashtag_status.json', {})
FA = load('freeagents.json', {'players': []})
STATE = load('hub_state.json', [])
LINEUPS = load('lineups.json', {'periods': {}})

TEAMID = {p['id']: p['abbrev'] for p in SCH['settings']['proTeams']}
def hub(a): return HUBABBR.get(a, a)
ABBR = {i: hub(a) for i, a in TEAMID.items()}

# ---- NBA games per scoring period -------------------------------------------------------------
GAMES = {}      # period -> {gameId: (startUTC, awayAbbr, homeAbbr)}
for t in SCH['settings']['proTeams']:
    for p, gl in t.get('proGamesByScoringPeriod', {}).items():
        for g in gl:
            GAMES.setdefault(int(p), {})[g['id']] = (dt.datetime.fromtimestamp(g['date'] / 1000, dt.timezone.utc), ABBR[g['awayProTeamId']], ABBR[g['homeProTeamId']])
TEAMGAME = {}   # (period, abbr) -> (opponent string, startUTC)
for p, gs in GAMES.items():
    for (st, aw, ho) in gs.values():
        TEAMGAME[(p, aw)] = ('@' + ho, st)
        TEAMGAME[(p, ho)] = (aw, st)

def pdate(p): return BASE + dt.timedelta(days=p - 1)
def plabel(p): d = pdate(p); return d.strftime('%a') + ' ' + str(d.day)
CUR = (now.astimezone(ET).date() - BASE).days + 1
def game_done(st): return st + dt.timedelta(hours=3) <= now
def day_done(p):
    if p < CUR - 1 and p not in GAMES: return True
    gs = GAMES.get(p, {})
    if p > CUR: return False
    if not gs: return p <= CUR
    return all(game_done(g[0]) for g in gs.values()) and p <= CUR

# ---- players -----------------------------------------------------------------------------------
HTBY = {norm(p['name']): p for p in HT.get('players', [])}
TEAMS = {t['id']: t for t in L['teams']}
SURN = {}

def stat(player, sid, key='appliedAverage', split=0, season=2027):
    for s in player.get('stats', []):
        if s.get('id') == f'{sid}{season}' and s.get('statSplitTypeId') == split:
            return s.get(key)
    return None

def info(entry, slot_override=None):
    pe = entry['playerPoolEntry']; pl = pe['player']
    name = pl['fullName']
    h = HTBY.get(norm(name))
    seas = stat(pl, '00'); esp = stat(pl, '10') or stat(pl, '10', season=2026)
    hb = h['fptsPerGame'] if h else None
    base_hb = hb if hb is not None else (esp if esp is not None else seas)
    if base_hb is None: base_hb = 0.0
    claude = 0.96 * (0.7 * base_hb + 0.3 * (seas if seas is not None else base_hb))
    slot = entry.get('lineupSlotId', 12) if slot_override is None else slot_override
    inj = entry.get('injuryStatus') or pl.get('injuryStatus') or 'ACTIVE'
    return dict(id=pl['id'], full=name, team=ABBR.get(pl.get('proTeamId'), '?'), elig=set(pl.get('eligibleSlots', [])),
                slot=slot, inj=inj, hb=base_hb, hb_raw=hb, esp=esp if esp is not None else base_hb, seas=seas, claude=claude,
                out=(slot == 13 or inj == 'OUT'))

def short(full, group):
    if full in NAME_OVERRIDE: return NAME_OVERRIDE[full]
    parts = full.split()
    last = parts[-1]
    if last.lower().rstrip('.') in ('jr', 'sr', 'ii', 'iii', 'iv') and len(parts) > 2: last = ' '.join(parts[-2:])
    others = [x for x in group if x != full and x.split()[-1] == full.split()[-1]]
    return (parts[0][0] + '. ' + last) if others else last

def roster_of(tid):
    return [info(e) for e in TEAMS[tid]['roster']['entries']]

def best_lineup(players, value):
    """players: list of dicts with 'elig'; value: function -> float. Max-sum assignment into the 10 starting slots."""
    n = len(players)
    vals = [value(p) for p in players]
    @functools.lru_cache(maxsize=None)
    def go(i, mask):
        if i == len(SLOTS): return (0.0, 0, ())
        best = go(i + 1, mask)          # leave slot empty
        best = (best[0], best[1], best[2])
        for k in range(n):
            if mask >> k & 1 or SLOTS[i] not in players[k]['elig']: continue
            sub = go(i + 1, mask | (1 << k))
            cand = (sub[0] + vals[k], sub[1] + 1, sub[2] + (k,))
            if cand[0] > best[0]: best = cand
        return best
    r = go(0, 0)
    return r[0], r[1], [players[k] for k in r[2]]

# ---- week structure -----------------------------------------------------------------------------
def my_matchups():
    out = {}
    for m in L['schedule']:
        if m['home']['teamId'] == ME or m['away']['teamId'] == ME:
            out[m['matchupPeriodId']] = m
    return out
MM = my_matchups()
def week_periods(wk):
    m = MM.get(wk)
    ks = sorted(int(k) for k in (m['home'].get('pointsByScoringPeriod') or {})) if m else []
    def to_sunday(a):
        n = 6 - pdate(a).weekday()          # days until Sunday
        return list(range(a, a + n + 1))
    if ks: return to_sunday(ks[0])
    prev = week_periods(wk - 1) if wk - 1 in MM else None
    if prev: return to_sunday(prev[-1] + 1)
    return []

def cur_week():
    for wk in sorted(MM):
        ps = week_periods(wk)
        if ps and ps[0] <= CUR <= ps[-1]: return wk
    return None

def sched_block(periods, nxt):
    teams = sorted(set(ABBR.values()))
    out = {}
    for t in teams:
        row = []
        for p in periods + ([nxt] if nxt else []):
            g = TEAMGAME.get((p, t)); row.append(g[0] if g else '')
        out[t] = row
    return out

def pts_split(m, tid):
    side = 'home' if m['home']['teamId'] == tid else 'away'
    return {int(k): v for k, v in (m[side].get('pointsByScoringPeriod') or {}).items()}

def box_actuals(p, tid):
    b = load(f'boxscores/{p}.json')
    res = {}
    if not b: return res
    for m in b.get('schedule', []):
        for side in ('home', 'away'):
            t = m[side]
            if t.get('teamId') == tid and t.get('rosterForCurrentScoringPeriod'):
                if t.get('pointsByScoringPeriod') and str(p) not in {str(k) for k in t['pointsByScoringPeriod']}: continue
                for e in t['rosterForCurrentScoringPeriod']['entries']:
                    res[e['playerPoolEntry']['player']['id']] = (e['playerPoolEntry'].get('appliedStatTotal'), e['lineupSlotId'])
    return res

def cet_label(t, year=True):
    t = t.astimezone(CET)
    return t.strftime('%a %b ') + str(t.day) + ((', %d' % t.year) if year else '') + t.strftime(', %H:%M %Z')

def phi(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))

def build_week(wk, prev, status_hint):
    m = MM[wk]; periods = week_periods(wk)
    oppid = m['away']['teamId'] if m['home']['teamId'] == ME else m['home']['teamId']
    opp = TEAMS[oppid]; oppname = opp['name'].strip()
    mepts = pts_split(m, ME); thpts = pts_split(m, oppid)
    me = roster_of(ME); th = roster_of(oppid)
    names = [p['full'] for p in me + th]
    for p in me + th: p['n'] = short(p['full'], names)
    nxt = periods[-1] + 1
    gamedays = [p for p in periods if GAMES.get(p)]
    live = status_hint == 'live'
    upcoming = status_hint == 'upcoming'
    # --- per day
    days = []; done_flags = []
    for p in periods:
        done = day_done(p) if not upcoming else False
        done_flags.append(done)
    last_done = max([p for p, d in zip(periods, done_flags) if d and GAMES.get(p)] or [0])
    def playing_usable(plist, p, after=None):
        pl = [x for x in plist if not x['out'] and (p, x['team']) in TEAMGAME and (after is None or TEAMGAME[(p, x['team'])][1] > after)]
        return pl, best_lineup(pl, lambda x: x['claude'])
    for i, p in enumerate(periods):
        d = {'label': plabel(p), 'done': done_flags[i]}
        for key, plist in (('me', me), ('them', th)):
            pl, (v, cnt, _) = playing_usable(plist, p)
            d[key] = [len(pl), cnt]
        d['pts'] = [mepts.get(p, 0), thpts.get(p, 0)] if done_flags[i] else None
        days.append(d)
    # keep earlier counts for finished days (they describe who actually could play then)
    if prev:
        for d, pd in zip(days, prev.get('days', [])):
            if d['done'] and pd.get('done'): d['me'], d['them'] = pd['me'], pd['them']
    totals = {'me': [sum(d['me'][0] for d in days), sum(d['me'][1] for d in days)],
              'them': [sum(d['them'][0] for d in days), sum(d['them'][1] for d in days)]}
    actual = {'me': sum(mepts.values()), 'them': sum(thpts.values())}
    # --- projections of the remaining games (game not yet started)
    rem_days = [p for p, d in zip(periods, done_flags) if not d and GAMES.get(p)]
    def remaining(plist, valf):
        tot = 0.0
        for p in rem_days:
            pl, _ = playing_usable(plist, p, after=now if p <= CUR else None)
            tot += best_lineup(pl, valf)[0]
        return tot
    open_days = max(len(rem_days), 0)
    stream = 0 if upcoming and False else min(50, round(8.3 * open_days))
    projs = {}
    for src, key in (('Claude', 'claude'), ('Hashtag Basketball', 'hb'), ('ESPN', 'esp')):
        mv = remaining(me, lambda x: x[key]); tv = remaining(th, lambda x: x[key])
        projs[src] = (mv, tv)
    def fin(src):
        mv, tv = projs[src]; add = stream if src == 'Claude' else 0
        return [round(actual['me'] + mv + add), round(actual['them'] + tv + add)]
    pf = {s: fin(s) for s in projs}
    lastlabel = plabel(last_done) if last_done else None
    through = ('Through ' + pdate(last_done).strftime('%a %b ') + str(pdate(last_done).day)) if last_done else 'Before tip-off'
    when = now.astimezone(CET).strftime('%a %b ') + str(now.astimezone(CET).day) + now.astimezone(CET).strftime(', %H:%M')
    # --- notes
    def inj_list(plist):
        return [f"{p['n']} ({'IR slot' if p['slot'] == 13 else p['inj'].lower().replace('_', '-')})" for p in plist if p['slot'] == 13 or p['inj'] not in ('ACTIVE', 'NORMAL')]
    def pfull(src, i): return pf[src][i]
    claude_me, claude_th = pf['Claude']
    diffs = [pf[s][0] - pf[s][1] for s in pf]
    sd = 38 * math.sqrt(open_days + 0.3)
    winprob = round(100 * phi((sum(diffs) / len(diffs)) / sd))
    if status_hint == 'final': winprob = 100 if actual['me'] > actual['them'] else 0
    # per player rows
    def player_rows(plist, tid):
        out = []
        prev_rows = {}
        if prev:
            for q in prev.get('players', {}).get('me' if tid == ME else 'opp', []): prev_rows[q['n']] = q
        actual_by_period = {p: box_actuals(p, tid) for p, d in zip(periods, done_flags) if d or p == CUR}
        for x in plist:
            g = []
            for i, p in enumerate(periods + [nxt]):
                tg = TEAMGAME.get((p, x['team']))
                if not tg: continue
                old = None
                for r in prev_rows.get(x['n'], {}).get('g', []):
                    if r[0] == i: old = r
                proj = old[2] if old else round(x['claude'], 1)
                rank = old[3] if old else None
                act = old[4] if old else None; started = old[5] if old else None
                if i < len(periods):
                    a = actual_by_period.get(p, {}).get(x['id'])
                    if a is not None and (done_flags[i] or p == CUR) and (a[0] or done_flags[i]):
                        act = round(a[0], 1) if a[0] is not None else None
                        started = 1 if (a[1] is not None and a[1] < 12) else 0
                g.append([i, tg[0], proj, rank, act, started])
            row = {'n': x['n'], 't': x['team'], 'p': [POS[s] for s in sorted(x['elig']) if s in POS], 'hb': round(x['hb'], 1), 'le': None}
            if x['out']: row['out'] = True
            row['g'] = g
            out.append(row)
        return out
    pm = player_rows(me, ME); po = player_rows(th, oppid)
    # --- adds
    acq = TEAMS[ME]['transactionCounter'].get('matchupAcquisitionTotals', {}) or {}
    used = int(acq.get(str(wk), 0))
    lim = int(math.floor(ADDS_PER_DAY * len(gamedays) + 1e-6))
    oppused = int((TEAMS[oppid]['transactionCounter'].get('matchupAcquisitionTotals', {}) or {}).get(str(wk), 0))
    # --- notes
    tcm_notes = []; opp_notes = []
    if last_done:
        bx = box_actuals(last_done, ME)
        top = sorted([(v[0] or 0, next((q['n'] for q in me if q['id'] == k), '?')) for k, v in bx.items() if v[0]], reverse=True)[:4]
        if top: tcm_notes.append(f"{plabel(last_done)}: TCM scored {mepts.get(last_done, 0)}. Best: " + ', '.join(f"{n} {round(v)}" for v, n in top) + '.')
        bo = box_actuals(last_done, oppid)
        topo = sorted([(v[0] or 0, next((q['n'] for q in th if q['id'] == k), '?')) for k, v in bo.items() if v[0]], reverse=True)[:4]
        if topo: opp_notes.append(f"{plabel(last_done)}: {opp['abbrev'] if 'abbrev' in opp else oppname} scored {thpts.get(last_done, 0)}. Best: " + ', '.join(f"{n} {round(v)}" for v, n in topo) + '.')
    tcm_notes.append(f"Adds: {used} of {lim} used this week ({lim - used} left; limit = 5/7 per game day, {len(gamedays)} game days).")
    il = inj_list(me)
    if il: tcm_notes.append('Injuries / IR: ' + ', '.join(il) + '.')
    # lineup check for today and tomorrow (ESPN lineups pulled by the loop)
    for p in (CUR, CUR + 1):
        lp = (LINEUPS.get('periods') or {}).get(str(p), {}).get(str(ME))
        if not lp or p not in periods or day_done(p): continue
        names_team = {q['full']: q['team'] for q in me}
        bench = [x['name'] for x in lp if x['slot'] == 12 and x['inj'] != 'OUT' and (p, names_team.get(x['name'])) in TEAMGAME]
        nogame = [x['name'] for x in lp if (x['slot'] in (0, 1, 2, 3, 4, 5, 6, 11)) and (p, names_team.get(x['name'])) not in TEAMGAME]
        if bench and nogame:
            tcm_notes.append(f"Lineup check {plabel(p)}: {', '.join(bench)} on the bench has a game while {', '.join(nogame)} in a starting slot does not.")
    left = ', '.join(f"{d['label'].split()[0]} {d['me'][0]}" + (f" ({d['me'][1]} usable)" if d['me'][0] > d['me'][1] else '') for d, f in zip(days, done_flags) if not f)
    if left: tcm_notes.append('Games left (players with a game): ' + left + '.')
    il2 = inj_list(th)
    if il2: opp_notes.append('Injuries / IR: ' + ', '.join(il2) + '.')
    opp_notes.append(f"Adds used this week: {oppused}.")
    leftt = ', '.join(f"{d['label'].split()[0]} {d['them'][0]}" for d, f in zip(days, done_flags) if not f)
    if leftt: opp_notes.append('Games left: ' + leftt + '.')
    # --- odd days
    daynotes = []
    for i, p in enumerate(periods):
        ng = len(GAMES.get(p, {}))
        d = days[i]
        if ng == 0:
            daynotes.append({'day': i, 'tag': 'No games', 'text': f"No NBA games on {d['label']}. Nobody scores; adds are scaled to game days, so the weekly add limit is lower."})
        elif ng <= 5:
            daynotes.append({'day': i, 'tag': 'Light slate', 'text': f"Only {ng} NBA games on {d['label']}. TCM has {d['me'][0]} players with a game ({10 - d['me'][1]} slots open), {oppname} has {d['them'][0]}. A day for streamers."})
        elif ng >= 12:
            daynotes.append({'day': i, 'tag': 'Heavy slate', 'text': f"{ng} NBA games on {d['label']}: TCM has {d['me'][0]} players with a game ({d['me'][1]} usable), {oppname} {d['them'][0]}. Check who sits."})
    # --- streamers: free agents for the remaining open-slot days
    streamers = []; plan = []
    open_idx = [i for i, (p, f) in enumerate(zip(periods, done_flags)) if not f and days[i]['me'][1] < 10 and GAMES.get(p)]
    cand = []
    for e in FA.get('players', []):
        pl = e['player']; name = pl['fullName']; tm = ABBR.get(pl.get('proTeamId'))
        if not tm or pl.get('injuryStatus') in ('OUT',): continue
        h = HTBY.get(norm(name)); esp = stat(pl, '10') or 0
        if not h: continue
        gd = [i for i in open_idx if (periods[i], tm) in TEAMGAME and (periods[i] != CUR or TEAMGAME[(periods[i], tm)][1] > now)]
        if not gd: continue
        l7 = stat(pl, '01', split=1); l15 = stat(pl, '02', split=2)
        base = 0.5 * h['fptsPerGame'] + 0.25 * esp + 0.25 * (l7 if l7 else h['fptsPerGame'])
        cand.append((base * len(gd), name, tm, pl, h, esp, l7, l15, gd))
    cand.sort(reverse=True, key=lambda c: c[0])
    for val, name, tm, pl, h, esp, l7, l15, gd in cand[:4]:
        pos = '/'.join(POS[s] for s in sorted(set(pl.get('eligibleSlots', [])) & set(POS)))
        pown = (pl.get('ownership') or {}).get('percentOwned') or 0
        nxt_game = TEAMGAME.get((nxt, tm))
        pg = sum(1 for p in range(133, 160) if (p, tm) in TEAMGAME)
        w = [sum(1 for p in range(s, s + 7) if (p, tm) in TEAMGAME) for s in (133, 140, 147, 154)]
        streamers.append({'player': name, 'team': tm, 'days': ', '.join(plabel(periods[i]).split()[0] for i in gd) + (f' ({nxt_game[0]} next Mon)' if nxt_game else ''),
                          'hb': round(h['fptsPerGame'], 1), 'espn': round(esp, 1), 'value': round(val),
                          'note': f"Free agent{' ' + pl.get('injuryStatus', '').lower().replace('_', '-') if pl.get('injuryStatus') not in (None, 'ACTIVE', 'NORMAL') else ''}, {pown:.0f}% owned. {pos}. Hashtag {h['fptsPerGame']:.1f}, ESPN {esp:.1f}"
                                  + (f", last 7 days {l7:.1f}" if l7 else '') + (f", last 15 {l15:.1f}" if l15 else '') + f". Games: {', '.join(plabel(periods[i]) for i in gd)}. {tm} games in W19-22: {'/'.join(map(str, w))}. Auto-picked by value over the open days; no manual research."})
    if open_idx:
        plan.append('Open-slot days: ' + ', '.join(f"{days[i]['label']} ({10 - days[i]['me'][1]} open)" for i in open_idx) + f". Adds left: {lim - used}.")
        if streamers: plan.append('Auto-ranked streamers below (best value over the open days). Check the status and your drop candidate on ESPN before adding.')
    plan.insert(0, f"Projected final (Claude): TCM {claude_me} - {claude_th} {opp['name'].strip()} ({'+' if claude_me - claude_th >= 0 else ''}{claude_me - claude_th}); Hashtag {pf['Hashtag Basketball'][0] - pf['Hashtag Basketball'][1]:+d}, ESPN {pf['ESPN'][0] - pf['ESPN'][1]:+d}.")
    # --- week object
    w = {'week': wk, 'dates': (pdate(periods[0]).strftime('%b ') + str(pdate(periods[0]).day) + '-' + (pdate(periods[-1]).strftime('%b ') if pdate(periods[-1]).month != pdate(periods[0]).month else '') + str(pdate(periods[-1]).day)),
         'opp': oppname, 'oppShort': ''.join(c for c in oppname if c.isupper())[:3] if sum(c.isupper() for c in oppname) >= 2 else oppname[:3].upper(),
         'status': status_hint, 'result': None}
    if prev: w['oppShort'] = prev['oppShort'] if prev['opp'] == oppname else w['oppShort']
    lead = 'leads' if actual['me'] > actual['them'] else ('trails' if actual['me'] < actual['them'] else 'is tied with')
    w['asOf'] = (f"Starts {plabel(periods[0])}." if upcoming else f"Live, updated {cet_label(now, False)}. {through}: TCM {lead} {oppname} {actual['me']}-{actual['them']}.") + ((' Injuries: ' + ', '.join(il) + '.') if il else '')
    w['dayNotes'] = daynotes
    w['actual'] = actual
    w['actualAsOf'] = ('No games played yet' if not last_done else f"{through} (updated {cet_label(now, False)})") + ('' if upcoming else '. ' + (f"{len(GAMES.get(CUR, {}))} NBA games on {plabel(CUR)}." if CUR in periods and not done_flags[periods.index(CUR)] else ''))
    w['winProb'] = winprob
    w['days'] = days; w['totals'] = totals
    notes = {'Claude': f"Real score {actual['me']}-{actual['them']} plus the rest of the week: best usable lineup per remaining day from each source's per-game numbers (Claude = 0.96 x (0.7 x Hashtag + 0.3 x this season's ESPN average)), plus ~{stream} points of streaming for both teams. Not adjusted for each opponent. Players in IR slots or OUT are not counted.",
             'Hashtag Basketball': f"Real score plus Hashtag Premium per-game points in your league scoring on the best usable lineup of the remaining days, no streams. Hashtag data: {'OK' if HTS.get('ok') else 'EXPIRED, renew the cookie'} (fetched {HTS.get('fetchedAt', '?')[:16].replace('T', ' ')} UTC).",
             'ESPN': 'Real score plus ESPN per-game projections (appliedAverage) on the best usable lineup of the remaining days, no streams.'}
    w['proj'] = [{'src': s, 'me': pf[s][0], 'them': pf[s][1], 'note': notes[s]} for s in pf] + [{'src': 'LineupExperts', 'me': None, 'them': None, 'note': "Not read: blocked by Cloudflare's bot check."}]
    plog = (prev or {}).get('projLog') or []
    pdaily = list((prev or {}).get('projDaily') or [])
    entry = {'when': when, 'asOf': through, 'actual': [actual['me'], actual['them']], 'p': {**{s: pf[s] for s in pf}, 'LineupExperts': None}}
    if status_hint == 'live' and not plog:
        first_tip = min((g[0] for g in GAMES.get(periods[0], {}).values()), default=None)
        late = first_tip is not None and now > first_tip
        plog = [{'when': when + (' (late lock, ' + now.astimezone(CET).strftime('%a') + ')' if late else ''), 'p': entry['p']}]
        if not last_done: pdaily = [{**entry, 'asOf': 'Before tip-off', 'actual': [0, 0]}]
    if status_hint == 'live':
        if pdaily and pdaily[-1]['asOf'] == through: pdaily[-1] = entry
        elif through != 'Before tip-off' or not pdaily: pdaily.append(entry)
    w['projLog'] = plog if status_hint != 'upcoming' else []
    w['projDaily'] = pdaily if status_hint != 'upcoming' else []
    w['players'] = {'src': 'Per-game points = Claude blend (0.96 x (0.7 x Hashtag Premium + 0.3 x ESPN season average)); hb = Hashtag Premium per game in your scoring. Opponent adjustment not applied (rank empty). LineupExperts blocked.', 'me': pm, 'opp': po}
    w['plan'] = plan; w['streamers'] = streamers
    w['sched'] = {'days': [[pdate(p).strftime('%a'), pdate(p).strftime('%b ') + str(pdate(p).day)] for p in periods],
                  'ext': [pdate(nxt).strftime('%a'), pdate(nxt).strftime('%b ') + str(pdate(nxt).day), 'W' + str(wk + 1)], 'teams': sched_block(periods, nxt)}
    w['rosters'] = {'me': [dict(n=x['n'], t=x['team'], p=[POS[s] for s in sorted(x['elig']) if s in POS], **({'out': True} if x['out'] else {})) for x in me],
                    'opp': [dict(n=x['n'], t=x['team'], p=[POS[s] for s in sorted(x['elig']) if s in POS], **({'out': True} if x['out'] else {})) for x in th]}
    w['notes'] = {'tcm': tcm_notes, 'opp': opp_notes, 'other': [f"Auto-built from ESPN/Hashtag data pulled {META.get('fetchedAt', '?')[:16].replace('T', ' ')} UTC. Projections are plain per-game math; streaming picks are auto-ranked, not researched."]}
    w['alert'] = None
    return w, dict(days=days, done=done_flags, periods=periods, last_done=last_done)


def finalize(prev):
    wk = prev['week']; m = MM[wk]; periods = week_periods(wk)
    mp = pts_split(m, ME); tp = pts_split(m, m['away']['teamId'] if m['home']['teamId'] == ME else m['home']['teamId'])
    w = json.loads(json.dumps(prev))
    w['status'] = 'final'; me_, th_ = sum(mp.values()), sum(tp.values())
    w['actual'] = {'me': me_, 'them': th_}; w['result'] = 'W' if me_ > th_ else ('L' if me_ < th_ else 'T')
    w['actualAsOf'] = 'Final'; w['winProb'] = 100 if me_ > th_ else (0 if me_ < th_ else 50)
    w['asOf'] = f"Final: TCM {me_}, {w['opp']} {th_} ({w['result']})."
    for i, p in enumerate(periods):
        w['days'][i]['done'] = True; w['days'][i]['pts'] = [mp.get(p, 0), tp.get(p, 0)]
        for side, tid in (('me', ME), ('opp', m['away']['teamId'] if m['home']['teamId'] == ME else m['home']['teamId'])):
            bx = box_actuals(p, tid)
            for q in w['players'][side]:
                for r in q['g']:
                    if r[0] == i and r[4] is None:
                        pid = next((x['id'] for x in roster_of(tid) if x['team'] == q['t'] and short(x['full'], [y['full'] for y in roster_of(tid)]) == q['n']), None)
                        if pid in bx: r[4] = round(bx[pid][0] or 0, 1); r[5] = 1 if bx[pid][1] < 12 else 0
    fin = {s: [me_, th_] for s in ('Claude', 'Hashtag Basketball', 'ESPN')}
    when = now.astimezone(CET).strftime('%a %b ') + str(now.astimezone(CET).day) + now.astimezone(CET).strftime(', %H:%M')
    w['projDaily'] = [x for x in w['projDaily'] if x['asOf'] != 'Final'] + [{'when': when, 'asOf': 'Final', 'actual': [me_, th_], 'p': {**fin, 'LineupExperts': None}}]
    w['proj'] = [{**x, 'me': (me_ if x['me'] is not None else None), 'them': (th_ if x['them'] is not None else None), 'note': x['note'] + ' (final)'} for x in w['proj']]
    w['alert'] = None; w['dayNotes'] = w.get('dayNotes', [])
    return w


def main():
    if now.astimezone(ET).date() > SEASON_END:
        print('season over'); return
    state = [w for w in STATE]
    wk = cur_week()
    problems = []
    age = None
    if META.get('fetchedAt'):
        age = (now - dt.datetime.fromisoformat(META['fetchedAt'].replace('Z', '+00:00'))).total_seconds() / 60
    if wk is None:
        print('no current matchup week found'); wk = max(MM)
    out = []
    by = {w['week']: w for w in state}
    # finalize any earlier live week
    for w in state:
        if w['week'] < wk and w['status'] != 'final':
            by[w['week']] = finalize(w)
    live, ctx = build_week(wk, by.get(wk), 'live')
    by[wk] = live
    # Fri-Sun: preview of next week
    nxt = wk + 1
    if nxt in MM and week_periods(nxt) and now.astimezone(ET).weekday() >= 4:
        by[nxt], _ = build_week(nxt, by.get(nxt), 'upcoming')
    elif nxt in by and by[nxt]['status'] == 'upcoming':
        pass
    # unfinished-games alert: latest NBA day that has started
    started_days = [p for p, gs in GAMES.items() if p <= CUR and any(g[0] <= now for g in gs.values())]
    alert = None
    if started_days:
        lp = max(started_days)
        un = [g for g in GAMES[lp].values() if not game_done(g[0])]
        if un and not (lp == CUR and now.astimezone(ET).hour < 12 and False):
            un.sort()
            end = max(g[0] for g in un) + dt.timedelta(hours=3)
            alert = (f"UNFINISHED: {', '.join(g[1] + ' at ' + g[2] for g in un)} not final at {now.astimezone(CET).strftime('%H:%M')} CET "
                     f"(estimated end {end.astimezone(CET).strftime('%H:%M')} CET), so {plabel(lp)}'s scores may be incomplete. Rerun after that.")
            live['alert'] = alert
    if age is not None and age > 60:
        live['alert'] = ((live['alert'] + ' ') if live['alert'] else '') + f"DATA STALE: the ESPN data loop last ran {int(age)} minutes ago. Restart 'ESPN data loop' in GitHub Actions."
    if not HTS.get('ok', True):
        live['alert'] = ((live['alert'] + ' ') if live['alert'] else '') + 'HASHTAG COOKIE EXPIRED: Hashtag numbers are old. Renew the cookie (7 steps) and rerun.'
    weeks = sorted(by, reverse=True)
    matchups = [by[k] for k in weeks]
    json.dump(matchups, open(D + 'hub_state.json', 'w'), separators=(',', ':'))
    upd = cet_label(now)
    js = ('var M_UPDATED = ' + json.dumps(upd) + ';\nvar M_SOURCES = ' + json.dumps(SOURCES) + ';\nvar MATCHUPS = ' + json.dumps(matchups, separators=(',', ':')) + ';\n')
    open(D + 'hub_matchups.js', 'w').write(js)
    p = {s['src']: s for s in live['proj']}
    lead = live['actual']
    summary = (f"Week {wk} vs {live['opp']}: TCM {lead['me']} - {lead['them']}. Projected final: Claude {p['Claude']['me']}-{p['Claude']['them']}, "
               f"Hashtag {p['Hashtag Basketball']['me']}-{p['Hashtag Basketball']['them']}, ESPN {p['ESPN']['me']}-{p['ESPN']['them']}. Win chance {live['winProb']}%.")
    follow = None
    if alert and started_days:
        un2 = [g for g in GAMES[max(started_days)].values() if not game_done(g[0])]
        if un2: follow = (max(g[0] for g in un2) + dt.timedelta(hours=3, minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    meta = {'followUpAt': follow, 'generatedAt': now.isoformat(), 'updatedLabel': upd, 'alert': live['alert'], 'dataAgeMinutes': None if age is None else round(age), 'summary': summary,
            'week': wk, 'adds': live['notes']['tcm'][[i for i, s in enumerate(live['notes']['tcm']) if s.startswith('Adds:')][0]]}
    json.dump(meta, open(D + 'hub_meta.json', 'w'), indent=1)
    print(summary); print('alert:', live['alert'])


if __name__ == '__main__':
    main()
