(() => {
    document.addEventListener("click", (event) => {
        const btn = event.target.closest("[data-fleet-copy]");
        if (!btn) return;
        event.preventDefault();
        const group = btn.closest("[data-fleet-copy-group]");
        const field = group && group.querySelector("[data-copy-value]");
        const value = field ? field.value : "";
        const icon = btn.querySelector("[data-copy-icon]");
        const flash = () => {
            if (!icon) return;
            icon.className = "bi bi-check2 text-success";
            btn.setAttribute("title", btn.getAttribute("data-copied-label") || "");
            setTimeout(() => {
                icon.className = "bi bi-clipboard";
                btn.setAttribute("title", btn.getAttribute("data-copy-label") || "");
            }, 1500);
        };
        const fallback = () => {
            const ta = document.createElement("textarea");
            ta.value = value;
            ta.setAttribute("readonly", "");
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            let copied = false;
            try { copied = document.execCommand("copy"); } catch (_) {}
            document.body.removeChild(ta);
            if (copied) flash();
        };
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(value).then(flash).catch(fallback);
        } else {
            fallback();
        }
    });

    // Reload the underlying overview when the enrollment token modal is closed,
    // so the fleet table reflects the agent's state once it has paired.
    document.addEventListener("click", (event) => {
        if (event.target.closest("[data-fleet-reload]")) {
            window.location.reload();
        }
    });

    const root = document.querySelector("[data-fleet-root]");
    const terminal = new Set(["succeeded", "failed", "cancelled"]);

    // Shared, null-safe helpers (the detail modal renders on pages with no root).
    const phaseFromRoot = (phase) =>
        (root && phase && root.getAttribute(`data-phase-${phase}`)) || phase || "";
    const rootOverdue = () => (root && root.dataset.labelOverdue) || "";

    // Operation rows inside an open detail modal advance in place.
    const pollOpenRows = async () => {
        const rows = Array.from(document.querySelectorAll("[data-operation-url]"));
        await Promise.all(rows.map(async (row) => {
            const stateNode = row.querySelector("[data-operation-state]");
            if (!stateNode || terminal.has(stateNode.textContent.trim())) return;
            try {
                const response = await fetch(row.dataset.operationUrl, {
                    headers: {Accept: "application/json"},
                });
                if (!response.ok) return;
                const data = await response.json();
                const status = data.status || {};
                stateNode.textContent = status.overdue ? (rootOverdue() || data.state) : data.state;
                stateNode.classList.toggle("text-danger", Boolean(status.overdue));
                const phaseNode = row.querySelector("[data-operation-phase]");
                if (phaseNode) phaseNode.textContent = phaseFromRoot(status.phase);
                const resultNode = row.querySelector("[data-operation-result]");
                if (resultNode) resultNode.textContent = JSON.stringify(data.result || {}, null, 2);
            } catch (_) {}
        }));
    };

    if (!root) {
        window.setInterval(pollOpenRows, 3000);
        return;
    }

    const strip = root.querySelector("[data-operations-strip]");
    const list = root.querySelector("[data-operations-list]");
    const count = root.querySelector("[data-operations-count]");
    const note = root.querySelector("[data-operations-note]");
    const feedUrl = root.dataset.operationsUrl;

    // Compact, language-neutral elapsed label (unit only, no sentence) so word
    // order never needs translating: 45s / 12m / 3h.
    const ago = (seconds) => {
        const s = Math.max(0, Math.floor(seconds || 0));
        if (s < 60) return `${s}s`;
        if (s < 3600) return `${Math.floor(s / 60)}m`;
        return `${Math.floor(s / 3600)}h`;
    };
    // The strip keeps queued work visible after its modal closes, so the single
    // page still reflects operations in flight across the whole fleet, and shows
    // enough — phase, elapsed, agent reachability — to tell progressing from stuck.
    const renderStrip = (operations) => {
        if (!strip || !list) return;
        list.textContent = "";
        let recreateExpected = false;
        operations.forEach((operation) => {
            const card = document.createElement("button");
            card.type = "button";
            card.className = "btn btn-sm text-start w-100 rounded-3 d-flex align-items-center gap-2 " +
                (operation.overdue ? "btn-outline-danger" : "btn-outline-secondary");
            card.dataset.dynamicModal = operation.detail_url;
            card.dataset.modalTitle = operation.project;

            const dot = document.createElement("span");
            dot.className = "dlux-online-dot " +
                (operation.agent_online ? "dlux-online-dot--on" : "dlux-online-dot--off");
            dot.title = operation.agent_online ? "online" : "offline";

            const name = document.createElement("span");
            name.className = "fw-semibold";
            name.textContent = operation.project;

            const meta = document.createElement("span");
            meta.className = "text-muted small flex-grow-1";
            const phase = phaseFromRoot(operation.phase);
            meta.textContent = ` · ${operation.action}` + (phase ? ` · ${phase}` : "");

            const badge = document.createElement("span");
            if (operation.overdue) {
                badge.className = "badge text-bg-danger";
                badge.textContent = root.dataset.labelOverdue || "overdue";
            } else {
                badge.className = "badge text-bg-info";
                badge.textContent = operation.state;
            }

            const clock = document.createElement("span");
            clock.className = "badge text-bg-light text-muted ms-1";
            clock.innerHTML = `<i class="bi bi-clock me-1"></i>${ago(operation.age_seconds)}`;

            card.append(dot, name, meta, badge, clock);
            list.appendChild(card);
            if (operation.recreate_expected) recreateExpected = true;
        });
        if (count) count.textContent = String(operations.length);
        strip.classList.toggle("d-none", operations.length === 0);
        if (note) {
            const show = recreateExpected && operations.length > 0;
            note.textContent = show ? (root.dataset.labelRecreate || "") : "";
            note.classList.toggle("d-none", !show);
        }
    };

    const pollFeed = async () => {
        if (!feedUrl) return;
        try {
            const response = await fetch(feedUrl, {
                headers: {Accept: "application/json", "X-Requested-With": "XMLHttpRequest"},
            });
            if (!response.ok) return;
            const data = await response.json();
            renderStrip(data.operations || []);
        } catch (_) {}
    };

    pollFeed();
    window.setInterval(() => {
        pollFeed();
        pollOpenRows();
    }, 3000);

    // Deep link: /fleet/?project=<uuid> opens that project's modal over the
    // table, so a shared link needs no separate detail page.
    const openUrl = (root.dataset.openProjectUrl || "").trim();
    if (openUrl) {
        document.body.dispatchEvent(new CustomEvent("dlux:dynamic_modal:open", {
            detail: {url: openUrl, title: root.dataset.openProjectName || "Project"},
        }));
    }
})();
