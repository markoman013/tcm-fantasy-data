#!/usr/bin/env python3
"""Usage: python3 inject_hub.py <live_page.html> <out.html>
Replaces only the three Weekly-Matchups variables (M_UPDATED, M_SOURCES, MATCHUPS) in the page with data/hub_matchups.js.
Every other tab and script stays exactly as it is."""
import re, sys
live, out = sys.argv[1], sys.argv[2]
s = open(live, encoding='utf-8').read()
if s.lstrip().lower().startswith('<!doctype'):          # saved copy of the live page carries the service wrapper: strip it
    i = s.lower().find('<body>'); s = s[i + 6:] if i >= 0 else s
    s = re.sub(r'</body>\s*</html>\s*$', '', s)
new = open('data/hub_matchups.js', encoding='utf-8').read().rstrip('\n')
pat = re.compile(r'var M_UPDATED = .*?\nvar M_SOURCES = .*?\nvar MATCHUPS = .*?\];[ \t]*(?=\n)', re.S)
m = pat.search(s)
if not m: sys.exit('markers not found in the live page')
s2 = s[:m.start()] + new + s[m.end():]
open(out, 'w', encoding='utf-8').write(s2)
print('ok', len(s), '->', len(s2))
