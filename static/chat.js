const chatBox = document.getElementById("chat-box");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

// data-zapas na chat-boxe = diskusia ku konkretnemu zapasu, inak globalny chat
const chatMatchId = chatBox.dataset.zapas || null;
const chatUrl = chatMatchId ? `/api/chat?zapas=${chatMatchId}` : "/api/chat";

let lastRendered = "";

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

async function loadMessages() {
    try {
        const resp = await fetch(chatUrl);
        if (!resp.ok) return;
        const messages = await resp.json();

        const html = messages.map(m => `
            <div class="chat-msg ${m.mine ? "chat-mine" : ""}">
                <div class="chat-bubble">
                    <div class="chat-meta">${m.crest ? `<img src="${m.crest}" alt="" class="crest crest-sm">` : ""}<a href="/hrac/${encodeURIComponent(m.user)}" class="player-link">${escapeHtml(m.user)}</a> · ${m.time}</div>
                    ${escapeHtml(m.text)}
                </div>
            </div>`).join("") || '<p class="text-muted text-center my-5">Zatiaľ žiadne správy — napíš prvú!</p>';

        if (html !== lastRendered) {
            const atBottom = chatBox.scrollHeight - chatBox.scrollTop - chatBox.clientHeight < 50;
            chatBox.innerHTML = html;
            lastRendered = html;
            if (atBottom) chatBox.scrollTop = chatBox.scrollHeight;
        }
    } catch (e) {
        console.error("Chyba pri načítaní chatu:", e);
    }
}

chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text) return;

    const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, match_id: chatMatchId ? parseInt(chatMatchId, 10) : null }),
    });
    if (resp.ok) {
        chatInput.value = "";
        await loadMessages();
        chatBox.scrollTop = chatBox.scrollHeight;
    }
});

loadMessages().then(() => { chatBox.scrollTop = chatBox.scrollHeight; });
setInterval(loadMessages, 3000);
