// Automaticka obnova LIVE skore kazdych 30 sekund (bez reloadu stranky).

const liveRegion = document.getElementById("live-region");

function escapeLive(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : text;
    return div.innerHTML;
}

async function refreshLive() {
    if (!liveRegion) return;
    try {
        const liga = liveRegion.dataset.liga || "WC";
        const resp = await fetch(`/api/live?liga=${encodeURIComponent(liga)}`);
        if (!resp.ok) return;
        const matches = await resp.json();

        if (!matches.length) {
            liveRegion.innerHTML = "";
            return;
        }

        let html = `<h5 class="section-title live-title"><span class="live-dot"></span> Práve sa hrá</h5>`;
        for (const m of matches) {
            html += `
            <a href="/zapas/${m.id}" class="text-decoration-none">
            <div class="match-card live-card">
                <div class="match-time"><span class="badge bg-danger">LIVE</span></div>
                <div class="match-teams">
                    <span class="team">${m.crest_home ? `<img src="${m.crest_home}" alt="" class="crest">` : ""}<span>${escapeLive(m.home)}</span></span>
                    <span class="live-score">${m.score_home} : ${m.score_away}</span>
                    <span class="team">${m.crest_away ? `<img src="${m.crest_away}" alt="" class="crest">` : ""}<span>${escapeLive(m.away)}</span></span>
                </div>
                <div class="match-meta">
                    ${m.group ? `<span class="badge bg-secondary">${escapeLive(m.group)}</span>` : ""}
                </div>
            </div>
            </a>`;
        }
        liveRegion.innerHTML = html;
    } catch (e) {
        // ticha chyba - skusime znova o 30 s
    }
}

if (liveRegion) {
    setInterval(refreshLive, 30000);
}
