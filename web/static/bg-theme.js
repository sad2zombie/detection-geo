// 页面切换时随机应用渐变背景主题
(function () {
    const THEMES = [
        {
            name: "aurora",
            baseA: "#040612",
            baseB: "#0a1835",
            baseC: "#061018",
            glowA: "rgba(0, 245, 255, 0.32)",
            glowB: "rgba(79, 195, 247, 0.22)",
            glowC: "rgba(191, 90, 242, 0.14)",
            grid: "rgba(0, 245, 255, 0.05)",
        },
        {
            name: "nebula",
            baseA: "#08051a",
            baseB: "#1a0a35",
            baseC: "#0c0618",
            glowA: "rgba(191, 90, 242, 0.35)",
            glowB: "rgba(255, 56, 150, 0.18)",
            glowC: "rgba(120, 80, 255, 0.12)",
            grid: "rgba(191, 90, 242, 0.05)",
        },
        {
            name: "emerald",
            baseA: "#030a08",
            baseB: "#062818",
            baseC: "#041210",
            glowA: "rgba(57, 255, 20, 0.2)",
            glowB: "rgba(0, 245, 200, 0.22)",
            glowC: "rgba(0, 180, 120, 0.1)",
            grid: "rgba(57, 255, 20, 0.04)",
        },
        {
            name: "sunset",
            baseA: "#120608",
            baseB: "#281018",
            baseC: "#180a10",
            glowA: "rgba(255, 120, 80, 0.28)",
            glowB: "rgba(255, 214, 10, 0.16)",
            glowC: "rgba(191, 90, 242, 0.12)",
            grid: "rgba(255, 150, 100, 0.04)",
        },
        {
            name: "ocean",
            baseA: "#020810",
            baseB: "#061828",
            baseC: "#030c14",
            glowA: "rgba(0, 150, 255, 0.3)",
            glowB: "rgba(0, 245, 255, 0.2)",
            glowC: "rgba(60, 100, 255, 0.12)",
            grid: "rgba(0, 180, 255, 0.045)",
        },
        {
            name: "violet",
            baseA: "#0a0518",
            baseB: "#180828",
            baseC: "#10041a",
            glowA: "rgba(160, 100, 255, 0.32)",
            glowB: "rgba(0, 245, 255, 0.15)",
            glowC: "rgba(255, 80, 200, 0.1)",
            grid: "rgba(160, 100, 255, 0.045)",
        },
        {
            name: "steel",
            baseA: "#06080c",
            baseB: "#101820",
            baseC: "#080a10",
            glowA: "rgba(180, 200, 220, 0.15)",
            glowB: "rgba(0, 245, 255, 0.18)",
            glowC: "rgba(100, 140, 200, 0.1)",
            grid: "rgba(180, 200, 220, 0.035)",
        },
        {
            name: "crimson",
            baseA: "#100408",
            baseB: "#200818",
            baseC: "#140610",
            glowA: "rgba(255, 56, 96, 0.25)",
            glowB: "rgba(191, 90, 242, 0.2)",
            glowC: "rgba(255, 120, 60, 0.1)",
            grid: "rgba(255, 80, 120, 0.04)",
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
