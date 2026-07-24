(function () {
    "use strict";

    var DEFAULT_NS = "fleet.overview_layout";

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : "";
    }

    function prefUrl(group, ns) {
        var template = group ? (group.getAttribute("data-app-pref-url-template") || "") : "";
        return (template && template.indexOf("__namespace__") !== -1)
            ? template.replace("__namespace__", encodeURIComponent(ns))
            : "";
    }

    function save(group, value) {
        var ns = (group && group.getAttribute("data-fleet-layout-ns")) || DEFAULT_NS;
        var url = prefUrl(group, ns);
        var token = csrfToken();
        if (!url || !token) return;
        fetch(url, {
            method: "POST",
            headers: {"X-CSRFToken": token, "Content-Type": "application/json"},
            body: JSON.stringify(value),
        }).then(function (response) {
            if (response.ok) window.location.reload();
        }).catch(function () {});
    }

    // Selector widget variant (radio inputs).
    document.addEventListener("change", function (e) {
        var input = e.target;
        if (!input || !input.matches || !input.matches('input[name="fleet_overview_layout"]')) return;
        if (!input.checked) return;
        save(input.closest("[data-fleet-layout-switch]"), input.value);
    });

    // Plain button-group fallback.
    document.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-fleet-layout-option]");
        if (!btn) return;
        e.preventDefault();
        if (btn.classList.contains("btn-primary")) return;
        save(btn.closest("[data-fleet-layout-switch]"), btn.getAttribute("data-fleet-layout-option"));
    });
})();
