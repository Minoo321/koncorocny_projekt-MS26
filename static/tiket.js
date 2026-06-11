// Tiket - vyber tipov ako v tipovacej kancelarii.
// Drzi sa v localStorage, takze prezije prepinanie dni aj sutazi.

const STORAGE_KEY = "tiket";

const panel = document.getElementById("tiket-panel");
const itemsBox = document.getElementById("tiket-items");
const emptyMsg = document.getElementById("tiket-empty");
const footer = document.getElementById("tiket-footer");
const countBadge = document.getElementById("tiket-count");
const totalEl = document.getElementById("tiket-total");
const submitBtn = document.getElementById("tiket-submit");
const clearBtn = document.getElementById("tiket-clear");
const msgEl = document.getElementById("tiket-msg");

let tiket = {};
try {
    tiket = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
} catch (e) {
    tiket = {};
}

// stranka bez tiket panela - skript nema co robit
if (!panel) {
    throw new Error("tiket panel nie je na stranke");
}

function save() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tiket));
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function syncButtons() {
    document.querySelectorAll(".js-odds").forEach(btn => {
        const entry = tiket[btn.dataset.matchId];
        btn.classList.toggle("active", !!entry && entry.vyber === btn.dataset.vyber);
    });
}

function render() {
    const entries = Object.entries(tiket);
    countBadge.textContent = entries.length;
    emptyMsg.hidden = entries.length > 0;
    footer.hidden = entries.length === 0;

    let total = 1;
    let html = "";
    for (const [matchId, e] of entries) {
        total *= parseFloat(e.odds);
        html += `
        <div class="tiket-item" data-match-id="${matchId}">
            <div class="d-flex justify-content-between align-items-start">
                <div class="me-1">
                    <div class="tiket-teams">${escapeHtml(e.home)} – ${escapeHtml(e.away)}</div>
                    <div class="text-secondary tiket-time">${escapeHtml(e.time)}</div>
                </div>
                <button type="button" class="btn-close btn-close-white tiket-remove" title="Odstrániť"></button>
            </div>
            <div class="d-flex justify-content-between align-items-center mt-1">
                <span class="badge bg-success">${e.vyber} · ${e.odds}</span>
                <span class="d-flex align-items-center gap-1 tiket-score">
                    <input type="number" class="form-control score-input score-h" min="0" max="20"
                           placeholder="–" title="Presné skóre (+5 b)" value="${e.sd ?? ""}">
                    :
                    <input type="number" class="form-control score-input score-a" min="0" max="20"
                           placeholder="–" value="${e.sh ?? ""}">
                </span>
            </div>
        </div>`;
    }
    itemsBox.querySelectorAll(".tiket-item").forEach(el => el.remove());
    itemsBox.insertAdjacentHTML("beforeend", html);
    totalEl.textContent = total.toFixed(2);
    syncButtons();
}

// klik na kurz pri zapase
document.querySelectorAll(".js-odds").forEach(btn => {
    btn.addEventListener("click", () => {
        const id = btn.dataset.matchId;
        const entry = tiket[id];
        if (entry && entry.vyber === btn.dataset.vyber) {
            delete tiket[id]; // druhy klik na ten isty kurz = odobratie
        } else {
            tiket[id] = {
                vyber: btn.dataset.vyber,
                odds: btn.dataset.odds,
                home: btn.dataset.home,
                away: btn.dataset.away,
                time: btn.dataset.time,
                sd: entry ? entry.sd : "",
                sh: entry ? entry.sh : "",
            };
        }
        save();
        render();
    });
});

// "Upravit" pri existujucom tipe - nacita ho na tiket, kde sa da zmenit
document.querySelectorAll(".js-edit-tip").forEach(btn => {
    btn.addEventListener("click", () => {
        const id = btn.dataset.matchId;
        tiket[id] = {
            vyber: btn.dataset.vyber,
            odds: btn.dataset.odds,
            home: btn.dataset.home,
            away: btn.dataset.away,
            time: btn.dataset.time,
            sd: btn.dataset.sd || "",
            sh: btn.dataset.sh || "",
        };
        save();
        render();
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
        msgEl.textContent = "Tip je na tikete — klikni na iný kurz pre zmenu a podaj tiket.";
    });
});

// presne skore + odstranenie poloziek (delegovane)
itemsBox.addEventListener("input", (e) => {
    const item = e.target.closest(".tiket-item");
    if (!item || !tiket[item.dataset.matchId]) return;
    const entry = tiket[item.dataset.matchId];
    if (e.target.classList.contains("score-h")) entry.sd = e.target.value;
    if (e.target.classList.contains("score-a")) entry.sh = e.target.value;
    save();
});

itemsBox.addEventListener("click", (e) => {
    if (!e.target.classList.contains("tiket-remove")) return;
    const item = e.target.closest(".tiket-item");
    delete tiket[item.dataset.matchId];
    save();
    render();
});

if (clearBtn) {
    clearBtn.addEventListener("click", () => {
        tiket = {};
        save();
        render();
    });
}

if (submitBtn) {
    submitBtn.addEventListener("click", async () => {
        const tipy = Object.entries(tiket).map(([matchId, e]) => ({
            match_id: parseInt(matchId, 10),
            vyber: e.vyber,
            skore_domaci: e.sd || null,
            skore_hostia: e.sh || null,
        }));
        if (!tipy.length) return;

        submitBtn.disabled = true;
        msgEl.textContent = "Podávam tiket…";
        try {
            const resp = await fetch("/api/tiket", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ tipy }),
            });
            if (resp.ok) {
                tiket = {};
                save();
                location.reload(); // flash sprava zo servera sa zobrazi po reloade
            } else {
                const data = await resp.json().catch(() => ({}));
                msgEl.textContent = data.error || "Tiket sa nepodarilo podať.";
                submitBtn.disabled = false;
            }
        } catch (err) {
            msgEl.textContent = "Chyba spojenia, skús znova.";
            submitBtn.disabled = false;
        }
    });
}

render();
