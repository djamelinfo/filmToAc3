(() => {
    const storageKey = "ac3fixer-theme";
    const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
    let preference = null;

    function readPreference() {
        try {
            const value = localStorage.getItem(storageKey);
            return value === "light" || value === "dark" ? value : null;
        } catch {
            return null;
        }
    }

    function applyTheme() {
        const theme = preference ?? (systemTheme.matches ? "dark" : "light");
        document.documentElement.dataset.theme = theme;
        for (const button of document.querySelectorAll("[data-theme-choice]")) {
            button.setAttribute("aria-pressed", String(button.dataset.themeChoice === theme));
        }
    }

    // Apply before the stylesheet loads to avoid a light flash on dark pages.
    preference = readPreference();
    applyTheme();

    document.addEventListener("DOMContentLoaded", () => {
        const controls = document.querySelector(".theme-switch");
        if (!controls) return;
        for (const button of controls.querySelectorAll("[data-theme-choice]")) {
            button.addEventListener("click", () => {
                preference = button.dataset.themeChoice;
                applyTheme();
                try {
                    localStorage.setItem(storageKey, preference);
                } catch {
                    // Switching still works when browser storage is unavailable.
                }
            });
        }
        applyTheme();
        controls.hidden = false;
    });

    systemTheme.addEventListener("change", () => {
        if (preference === null) applyTheme();
    });

    window.addEventListener("storage", event => {
        if (event.key === storageKey || event.key === null) {
            preference = readPreference();
            applyTheme();
        }
    });
})();
