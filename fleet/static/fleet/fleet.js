(() => {
    const root = document.querySelector("[data-fleet-root]");
    const terminal = new Set(["succeeded", "failed", "cancelled"]);

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
                stateNode.textContent = data.state;
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
    const feedUrl = root.dataset.operationsUrl;

    // The strip keeps queued work visible after its modal closes, so the single
    // page still reflects operations in flight across the whole fleet.
    const renderStrip = (operations) => {
        if (!strip || !list) return;
        list.textContent = "";
        operations.forEach((operation) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "btn btn-sm btn-outline-secondary rounded-pill";
            button.dataset.dynamicModal = operation.detail_url;
            button.dataset.modalTitle = operation.project;

            const name = document.createElement("span");
            name.className = "fw-semibold";
            name.textContent = operation.project;
            const action = document.createElement("span");
            action.className = "text-muted";
            action.textContent = ` · ${operation.action}`;
            const state = document.createElement("span");
            state.className = "badge text-bg-info ms-1";
            state.textContent = operation.state;

            button.append(name, action, state);
            list.appendChild(button);
        });
        if (count) count.textContent = String(operations.length);
        strip.classList.toggle("d-none", operations.length === 0);
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
