/* Julkar FundingRate — ArcBubbles-style UI logic */
(() => {
  const $ = (id) => document.getElementById(id);
  const apiBase = () => (window.FUNDARB_API || "").replace(/\/$/, "");

  async function api(path, params = {}) {
    const u = new URL((apiBase() || "") + path, window.location.origin);
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") u.searchParams.set(k, v);
    });
    const r = await fetch(u.toString(), { cache: "no-store" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  }

  function pct(x, digits = 4) {
    if (x === null || x === undefined || Number.isNaN(Number(x))) return "—";
    const v = Number(x) * 100;
    return (v > 0 ? "+" : "") + v.toFixed(digits) + "%";
  }

  function clsRate(x) {
    if (x > 0) return "pos";
    if (x < 0) return "neg";
    return "muted";
  }

  function fmtAge(s) {
    if (s == null) return "—";
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}m ${s % 60}s`;
  }

  // tabs = chips
  document.querySelectorAll("#tabs .chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#tabs .chip").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".panel-view").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $("panel-" + btn.dataset.tab).classList.add("active");
    });
  });

  let cache = { arb: null, matrix: null, rates: null, health: null };

  function renderArb() {
    const data = cache.arb;
    const body = $("arbBody");
    if (!data) {
      body.innerHTML = `<tr><td colspan="6" class="empty">Loading…</td></tr>`;
      return;
    }
    const q = ($("search").value || "").trim().toUpperCase();
    let rows = data.opportunities || [];
    if (q) rows = rows.filter((r) => r.base.includes(q));
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="6" class="empty">No arb above threshold</td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map((r) => {
        const venues = (r.venues || [])
          .map(
            (v) =>
              `<span class="vchip"><span class="ex">${v.exchange}</span> <span class="${clsRate(
                v.rate_8h
              )} mono">${pct(v.rate_8h, 4)}</span></span>`
          )
          .join("");
        return `<tr>
          <td><strong>${r.base}</strong></td>
          <td class="mono pos">${pct(r.spread_8h, 4)}</td>
          <td class="mono pos">${pct(r.spread_apy, 2)}</td>
          <td><span class="pill-row"><span class="ex">${r.long_exchange}</span><span class="mono ${clsRate(
            r.long_rate_8h
          )}">${pct(r.long_rate_8h, 4)}</span></span></td>
          <td><span class="pill-row"><span class="ex">${r.short_exchange}</span><span class="mono ${clsRate(
            r.short_rate_8h
          )}">${pct(r.short_rate_8h, 4)}</span></span></td>
          <td><div class="venues">${venues}</div></td>
        </tr>`;
      })
      .join("");
  }

  function renderMatrix() {
    const data = cache.matrix;
    if (!data) {
      $("matrixHead").innerHTML = "";
      $("matrixBody").innerHTML = `<tr><td class="empty">Loading…</td></tr>`;
      return;
    }
    const exs = data.exchanges || [];
    const q = ($("search").value || "").trim().toUpperCase();
    let bases = data.bases || [];
    if (q) bases = bases.filter((b) => b.base.includes(q));

    $("matrixHead").innerHTML = `<tr><th>BASE</th>${exs
      .map((e) => `<th>${e}</th>`)
      .join("")}</tr>`;

    $("matrixBody").innerHTML = bases
      .map((b) => {
        const rates = exs.map((e) => b.venues[e]?.rate_8h);
        const nums = rates.filter((x) => typeof x === "number");
        const hi = nums.length ? Math.max(...nums) : null;
        const lo = nums.length ? Math.min(...nums) : null;
        const cells = exs
          .map((e) => {
            const v = b.venues[e];
            if (!v) return `<td class="rate muted">—</td>`;
            let extra = "";
            if (hi !== null && v.rate_8h === hi && hi !== lo) extra = " hi";
            if (lo !== null && v.rate_8h === lo && hi !== lo) extra = " lo";
            return `<td class="rate ${clsRate(v.rate_8h)}${extra}" title="${v.symbol}">${pct(
              v.rate_8h,
              4
            )}</td>`;
          })
          .join("");
        return `<tr><td class="base">${b.base}</td>${cells}</tr>`;
      })
      .join("");
  }

  function renderRates() {
    const data = cache.rates;
    const body = $("ratesBody");
    if (!data) {
      body.innerHTML = `<tr><td colspan="8" class="empty">Loading…</td></tr>`;
      return;
    }
    const q = ($("search").value || "").trim().toUpperCase();
    const ex = $("exFilter").value;
    let rows = data.rows || [];
    if (ex) rows = rows.filter((r) => r.exchange === ex);
    if (q) {
      rows = rows.filter(
        (r) => r.base.includes(q) || (r.symbol || "").toUpperCase().includes(q)
      );
    }
    rows = rows.slice(0, 500);
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="8" class="empty">No rows</td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map(
        (r) => `<tr>
        <td><strong>${r.base}</strong></td>
        <td class="ex">${r.exchange}</td>
        <td class="muted">${r.symbol}</td>
        <td class="mono ${clsRate(r.rate_8h)}">${pct(r.rate_8h, 4)}</td>
        <td class="mono ${clsRate(r.rate_1h)}">${pct(r.rate_1h, 5)}</td>
        <td class="mono ${clsRate(r.rate_apy)}">${pct(r.rate_apy, 2)}</td>
        <td class="mono muted">${
          r.mark != null
            ? Number(r.mark).toLocaleString(undefined, { maximumFractionDigits: 6 })
            : "—"
        }</td>
        <td class="muted">${r.interval_h}h</td>
      </tr>`
      )
      .join("");
  }

  function renderSide() {
    const h = cache.health || {};
    const arb = cache.arb || {};
    $("sRows").textContent = h.n_rows ?? "—";
    $("sPoll").textContent = h.poll_ms != null ? `${Math.round(h.poll_ms)}ms` : "—";
    $("sAge").textContent = fmtAge(h.age_s);
    $("sArbs").textContent = arb.n ?? "—";
    $("sideTitle").textContent = "LIVE";
    $("sideMeta").textContent = h.ok
      ? `poll #${h.poll_n || 0} · ${fmtAge(h.age_s)} ago`
      : "API offline / connecting";
    const counts = h.counts || {};
    $("exList").innerHTML = Object.keys(counts).length
      ? Object.entries(counts)
          .map(([k, v]) => `<div>${k.toUpperCase()}<b>${v}</b></div>`)
          .join("")
      : "—";
    $("counts").textContent = Object.entries(counts)
      .map(([k, v]) => `${k}:${v}`)
      .join(" · ");
  }

  function renderAll() {
    renderArb();
    renderMatrix();
    renderRates();
    renderSide();
  }

  async function load() {
    const minBps = Number($("minBps").value || 0.5);
    try {
      const [health, arb, matrix, rates] = await Promise.all([
        api("/api/health"),
        api("/api/arb", { min_spread_bps: minBps, limit: 300 }),
        api("/api/matrix", { limit_bases: 120 }),
        api("/api/rates", { limit: 3000 }),
      ]);
      cache = { health, arb, matrix, rates };
      $("statusText").textContent = `LIVE · ${fmtAge(health.age_s)} · ${health.n_rows} ROWS`;
      renderAll();
    } catch (e) {
      $("statusText").textContent = `ERR ${e.message}`;
      $("sideMeta").textContent = String(e.message);
    }
  }

  $("search").addEventListener("input", renderAll);
  $("exFilter").addEventListener("change", renderRates);
  $("minBps").addEventListener("change", load);
  $("refresh").addEventListener("click", load);

  load();
  setInterval(load, 15000);
})();
