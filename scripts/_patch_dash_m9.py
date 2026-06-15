from pathlib import Path
p = Path("monitoring/dashboard_m9.html")
text = p.read_text(encoding="utf-8")
if "operator_control_plane" in text:
    print("already patched")
    raise SystemExit(0)
inject_css = """  #do-not-claim-banner { background: #3a1b1b; border: 1px solid var(--red); border-radius: 6px; padding: 10px 14px; margin-bottom: 12px; color: var(--red); font-weight: bold; }
  #do-not-claim-banner.hidden { display: none; }
  .verdict-row { font-size: 12px; color: var(--muted); margin-bottom: 8px; }
  .verdict-row span { margin-right: 10px; }
"""
text = text.replace("  #last-refresh { font-size: 11px; color: var(--muted); margin-top: 4px; }", inject_css + "  #last-refresh { font-size: 11px; color: var(--muted); margin-top: 4px; }")
panels = """<div id=\"do-not-claim-banner\" class=\"hidden\"></div>
<div id=\"verdict-labels\" class=\"verdict-row\"></div>

<h2>Layer Ownership (blocker owner)</h2>
<table id=\"layer-ownership-table\">
  <thead><tr><th>Layer</th><th>Status</th><th>Blocker owner</th></tr></thead>
  <tbody id=\"layer-ownership-body\"></tbody>
</table>

<h2>Cycle Length Health (2 / 3 / 4 leg)</h2>
<table id=\"cycle-length-table\">
  <thead><tr><th>Legs</th><th>Discovery</th><th>Found</th><th>Quoteable</th></tr></thead>
  <tbody id=\"cycle-length-body\"></tbody>
</table>

<h2>Quarantine Impact</h2>
<div class=\"row\" id=\"quarantine-row\"></div>

<h2>Top Blockers</h2>
<table id=\"blockers-table\">
  <thead><tr><th>Reason</th><th>Count</th><th>Owner</th></tr></thead>
  <tbody id=\"blockers-body\"></tbody>
</table>

<h2>QSR Semantics</h2>
<div id=\"qsr-semantics\" class=\"verdict-row\"></div>

<h2>Freshness</h2>
<div class=\"row\" id=\"freshness-row\"></div>

"""
text = text.replace("</div>\n\n<h2>Scan Coverage</h2>", "</div>\n\n" + panels + "<h2>Scan Coverage</h2>", 1)
js = """
  const ocp = d.operator_control_plane || {};
  const dnc = ocp.do_not_claim || {};
  const ban = document.getElementById('do-not-claim-banner');
  if (dnc.active) {
    ban.classList.remove('hidden');
    ban.textContent = dnc.banner || 'DO NOT CLAIM economics / profit-ready';
  } else {
    ban.classList.add('hidden');
    ban.textContent = '';
  }
  const vl = (ocp.verdict_labels || []).map(l => badge(l, l.includes('NOT') ? 'red' : (l.includes('PARTIAL') ? 'yellow' : 'green'))).join(' ');
  document.getElementById('verdict-labels').innerHTML = vl || '<span class=\"neu\">No operator verdict loaded</span>';
  const lob = document.getElementById('layer-ownership-body');
  const layers = ocp.layer_ownership || [];
  lob.innerHTML = layers.length ? layers.map(r => `<tr><td>${r.layer}</td><td>${gateBadge(r.status)}</td><td>${r.blocker_owner || '-'}</td></tr>`).join('') : '<tr><td colspan=\"3\" class=\"neu\">-</td></tr>';
  const clh = ocp.cycle_length_health || {};
  document.getElementById('cycle-length-body').innerHTML = ['2','3','4'].map(leg => {
    const row = clh[leg] || {};
    return `<tr><td>${leg}-leg</td><td>${row.discovery ?? '-'}</td><td>${row.found ?? '-'}</td><td>${row.quoteable ?? '-'}</td></tr>`;
  }).join('');
  const qi = ocp.quarantine_impact || {};
  document.getElementById('quarantine-row').innerHTML = [
    card('Before quarantine', qi.cycles_before ?? '-', ''),
    card('After quarantine', qi.cycles_after ?? '-', ''),
    card('Probe off', qi.probe_off_cycles ?? '-', ''),
    card('Probe production', qi.probe_production_cycles ?? '-', ''),
    card('Hard exclude', qi.hard_exclude_total ?? '-', ''),
  ].join('');
  const blockers = ocp.top_blockers || [];
  document.getElementById('blockers-body').innerHTML = blockers.length ? blockers.map(b => `<tr><td>${b.reason}</td><td>${b.count}</td><td>${b.owner || ocp.primary_blocker_owner || '-'}</td></tr>`).join('') : '<tr><td colspan=\"3\" class=\"neu\">-</td></tr>';
  const qs = ocp.qsr_semantics || {};
  document.getElementById('qsr-semantics').innerHTML = ['qsr','qsr_liveness','qsr_econ'].map(k => `<span><b>${k}</b>: ${qs[k] || '-'}</span>`).join('');
  const fr = ocp.freshness || {};
  document.getElementById('freshness-row').innerHTML = [
    card('handoff_ready', fr.handoff_ready === true ? 'YES' : (fr.handoff_ready === false ? 'NO' : '-'), fr.handoff_ready ? 'pos' : 'neg'),
    card('m8_stale', fr.m8_stale === true ? 'YES' : 'NO', fr.m8_stale ? 'neg' : 'pos'),
    card('duration_fulfilled', fr.duration_fulfilled === true ? 'YES' : 'NO', fr.duration_fulfilled ? 'pos' : 'neg'),
    `<div class=\"card\"><div class=\"label\">artifact</div><div class=\"val\" style=\"font-size:10px\">${d.artifact_source_path || fr.artifact_path_hint || '-'}</div></div>`,
  ].join('');

"""
text = text.replace("  // Header status", js + "\n  // Header status", 1)
old = "card('QSR', ec.qsr != null ? ec.qsr.toFixed(3) : '\u2014', ec.qsr >= 0.85 ? 'pos' : 'neg'),"
new = old + "\n    card('qsr_liveness', ec.qsr_liveness != null ? Number(ec.qsr_liveness).toFixed(3) : '\u2014', ''),\n    card('qsr_econ', ec.qsr_econ != null ? Number(ec.qsr_econ).toFixed(3) : '\u2014', ''),"
if old in text:
    text = text.replace(old, new)
p.write_text(text, encoding="utf-8")
print("patched")
