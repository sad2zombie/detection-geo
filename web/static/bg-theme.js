// 页面切换时随机应用渐变背景主题
(function () {
    const THEMES = [
        {
            name: "aurora",
            baseA: "#0a1020",
            baseB: "#122848",
            baseC: "#0a1a28",
            glowA: "rgba(0, 245, 255, 0.38)",
            glowB: "rgba(79, 195, 247, 0.28)",
            glowC: "rgba(191, 90, 242, 0.20)",
            grid: "rgba(0, 245, 255, 0.08)",
        },
        {
            name: "nebula",
            baseA: "#100a28",
            baseB: "#281248",
            baseC: "#140a28",
            glowA: "rgba(191, 90, 242, 0.40)",
            glowB: "rgba(255, 56, 150, 0.24)",
            glowC: "rgba(120, 80, 255, 0.18)",
            grid: "rgba(191, 90, 242, 0.08)",
        },
        {
            name: "emerald",
            baseA: "#061410",
            baseB: "#0a3828",
            baseC: "#061e18",
            glowA: "rgba(57, 255, 20, 0.28)",
            glowB: "rgba(0, 245, 200, 0.28)",
            glowC: "rgba(0, 180, 120, 0.16)",
            grid: "rgba(57, 255, 20, 0.07)",
        },
        {
            name: "sunset",
            baseA: "#1e0a10",
            baseB: "#381828",
            baseC: "#240e18",
            glowA: "rgba(255, 120, 80, 0.35)",
            glowB: "rgba(255, 214, 10, 0.22)",
            glowC: "rgba(191, 90, 242, 0.18)",
            grid: "rgba(255, 150, 100, 0.07)",
        },
        {
            name: "ocean",
            baseA: "#061020",
            baseB: "#0a2840",
            baseC: "#061828",
            glowA: "rgba(0, 150, 255, 0.36)",
            glowB: "rgba(0, 245, 255, 0.28)",
            glowC: "rgba(60, 100, 255, 0.18)",
            grid: "rgba(0, 180, 255, 0.07)",
        },
        {
            name: "violet",
            baseA: "#120a28",
            baseB: "#241040",
            baseC: "#18082e",
            glowA: "rgba(160, 100, 255, 0.38)",
            glowB: "rgba(0, 245, 255, 0.22)",
            glowC: "rgba(255, 80, 200, 0.16)",
            grid: "rgba(160, 100, 255, 0.07)",
        },
        {
            name: "steel",
            baseA: "#0a1018",
            baseB: "#182838",
            baseC: "#0e1420",
            glowA: "rgba(180, 200, 220, 0.22)",
            glowB: "rgba(0, 245, 255, 0.24)",
            glowC: "rgba(100, 140, 200, 0.16)",
            grid: "rgba(180, 200, 220, 0.06)",
        },
        {
            name: "crimson",
            baseA: "#1a0810",
            baseB: "#301028",
            baseC: "#200a18",
            glowA: "rgba(255, 56, 96, 0.32)",
            glowB: "rgba(191, 90, 242, 0.26)",
            glowC: "rgba(255, 120, 60, 0.16)",
            grid: "rgba(255, 80, 120, 0.07)",
        },
    ];

    function pickTheme() {
        const last = sessionStorage.getItem("bg-theme-last");
        let pool = THEMES;
        if (last && THEMES.length > 1) {
            const filtered = THEMES.filter((t) => t.name !== last);
            if (filtered.length) pool = filtered;
        }
        const theme = pool[Math.floor(Math.random() * pool.length)];
        sessionStorage.setItem("bg-theme-last", theme.name);
        return theme;
    }

    function applyTheme(theme) {
        const root = document.documentElement;
        root.style.setProperty("--bg-base-a", theme.baseA);
        root.style.setProperty("--bg-base-b", theme.baseB);
        root.style.setProperty("--bg-base-c", theme.baseC);
        root.style.setProperty("--bg-glow-a", theme.glowA);
        root.style.setProperty("--bg-glow-b", theme.glowB);
        root.style.setProperty("--bg-glow-c", theme.glowC);
        root.style.setProperty("--bg-grid-color", theme.grid);
        document.body.dataset.bgTheme = theme.name;
    }

    applyTheme(pickTheme());
})();
