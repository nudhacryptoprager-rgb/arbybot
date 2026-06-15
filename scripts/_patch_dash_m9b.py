from pathlib import Path
p = Path("monitoring/dashboard_m9.html")
text = p.read_text(encoding="utf-8")
if "operator_warnings" not in text:
    inject = """
<h2>Operator Warnings</h2>
<div id="operator-warnings"></div>

<h2>Size Ladder</h2>
<div class="row" id="size-ladder-row"></div>

<h2>Top Losing Leg</h2>
<div id="top-losing-leg" class="verdict-row"></div>

"""
    text = text.replace("<h2>Scan Coverage</h2>", inject + "<h2>Scan Coverage</h2>", 1)
    js = """
  const warns = ocp.operator_warnings || [];
  const ow = document.getElementById('operator-warnings');
  ow.innerHTML = warns.length ? warns.map(w => `<span class="badge badge-red">${w}</span>`).join(' ') : '<span class="neu">none</span>';
  const sl = ocp.size_ladder || {};
  document.getElementById('size-ladder-row').innerHTML = [
    card('sizes_usd', Array.isArray(sl.sizes_usd) ? sl.sizes_usd.join(',') : '-', ''),
    card('dynamic_size', sl.dynamic_size_enabled === true ? 'ON' : (sl.dynamic_size_enabled === false ? 'OFF' : '-'), ''),
    card('selected_sample', (sl.selected_sizes_sample || []).join(',') || '-', ''),
  ].join('');
  const tll = ocp.top_losing_leg;
  document.getElementById('top-losing-leg').innerHTML = tll ? `<span><b>${tll.dex_id || tll.adapter_type}</b> ${tll.token_in}->${tll.token_out} ratio=${tll.norm_value_ratio} cycle=${tll.cycle_id || '-'}</span>` : '<span class="neu">-</span>';
  const av = ocp.artifact_validity || {};
  if (av.duration_fulfilled === false) {
    ban.classList.remove('hidden');
    ban.textContent = (ban.textContent || '') + ' | ARTIFACT INCOMPLETE';
  }

"""
    text = text.replace("  const ocp = d.operator_control_plane || {};", "  const ocp = d.operator_control_plane || {};\n" + js, 1)
    p.write_text(text, encoding="utf-8")
    print("patched warnings")
else:
    print("already patched")
