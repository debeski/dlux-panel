(() => {
    const rows = Array.from(document.querySelectorAll("[data-operation-url]"));
    if (!rows.length) return;
    const terminal = new Set(["succeeded", "failed", "cancelled"]);
    const refresh = async () => {
        await Promise.all(rows.map(async (row) => {
            const stateNode = row.querySelector("[data-operation-state]");
            if (!stateNode || terminal.has(stateNode.textContent.trim())) return;
            try {
                const response = await fetch(row.dataset.operationUrl, {headers: {Accept: "application/json"}});
                if (!response.ok) return;
                const data = await response.json();
                stateNode.textContent = data.state;
                const resultNode = row.querySelector("[data-operation-result]");
                if (resultNode) resultNode.textContent = JSON.stringify(data.result || {}, null, 2);
            } catch (_) {}
        }));
    };
    window.setInterval(refresh, 3000);
})();
