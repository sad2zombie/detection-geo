// 品牌匹配分析报告渲染（首页与任务管理页共用）
(function () {
    const PLATFORM_ANALYSIS_CONFIG = {
        official_website: { title: "品牌官网", kind: "brand-website", level: 1 },
        douyin: { title: "抖音蓝V账号（粉丝排名前3）", kind: "users-table", level: 2, idKey: "douyin_id", idLabel: "抖音号" },
        xiaohongshu: { title: "小红书企业认证账号（粉丝排名前3）", kind: "users-table", level: 2, idKey: "xhs_id", idLabel: "小红书号" },
        jd: { title: "京东官方旗舰店", kind: "shop-row", level: 2, nameLabel: "店铺名称" },
        taobao: { title: "淘宝官方旗舰店", kind: "shop-row", level: 2, nameLabel: "店铺名称" },
        baidu: { title: "百度信息密度评估", kind: "score-row", level: 3 },
    };

    const SOURCE_LEVEL_LABELS = {
        1: "一级信源（官方网站）",
        2: "二级信源（平台官方账号）",
        3: "三级信源（搜索引擎）",
    };

    function renderAnalysisUsersTable(r, cfg) {
        const users = r.users || [];
        const cols = `
        <th style="padding:8px;">#</th>
        <th style="padding:8px;">名称</th>
        <th style="padding:8px;">${cfg.idLabel}</th>
        <th style="padding:8px;">主页链接</th>`;
        const rows = users.length
            ? users.map((u, i) => `
            <tr>
                <td style="padding:8px;">${i + 1}</td>
                <td style="padding:8px;">${u.name || "-"}</td>
                <td style="padding:8px;">${u[cfg.idKey] || "-"}</td>
                <td style="padding:8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${u.profile_url ? `<a href="${u.profile_url}" data-platform="${r.platform}" class="profile-link" target="_blank">${u.profile_url}</a>` : "-"}</td>
            </tr>`).join("")
            : "";
        return `
        <h3 style="margin-top:24px;">${cfg.title}</h3>
        ${users.length
            ? `<table style="width:100%; border-collapse:collapse;">
                <thead><tr style="text-align:left; border-bottom:1px solid var(--border);">${cols}</tr></thead>
                <tbody>${rows}</tbody>
            </table>`
            : `<p style="color:var(--text-secondary);padding:8px 0;">无</p>`}
    `;
    }

    function renderAnalysisScoreRow(r, cfg) {
        return `
        <h3 style="margin-top:24px;">${cfg.title}</h3>
        <table style="width:100%; border-collapse:collapse;">
            <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">平台</th><th style="padding:8px;">匹配得分</th><th style="padding:8px;">评价</th></tr></thead>
            <tbody><tr><td>${r.platform}</td><td>${r.score ?? "-"}</td><td>${r.assessment_grade || "-"}</td></tr></tbody>
        </table>
    `;
    }

    function renderAnalysisShopRow(r, cfg) {
        return `
        <h3 style="margin-top:24px;">${cfg.title}</h3>
        ${r.name
            ? `<table style="width:100%; border-collapse:collapse;">
                <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">${cfg.nameLabel}</th><th style="padding:8px;">${cfg.nameLabel.replace("名称", "链接")}</th></tr></thead>
                <tbody><tr>
                    <td style="padding:8px;">${r.name}</td>
                    <td style="padding:8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${r.profile_url ? `<a href="${r.profile_url}" data-platform="${r.platform}" class="profile-link" target="_blank">${r.profile_url}</a>` : "-"}</td>
                </tr></tbody>
            </table>`
            : `<p style="color:var(--text-secondary);padding:8px 0;">无</p>`}
    `;
    }

    function renderBrandWebsite(r, cfg) {
        const hasWebsite = r.website && r.website !== "未找到";
        const sourceLabel = r.source || "-";
        return `
        <h3 style="margin-top:24px;">${cfg.title}</h3>
        <table style="width:100%; border-collapse:collapse;">
            <thead><tr style="text-align:left; border-bottom:1px solid var(--border);">
                <th style="padding:8px;">品牌名称</th>
                <th style="padding:8px;">官网地址</th>
                <th style="padding:8px;">品牌简介</th>
            </tr></thead>
            <tbody><tr>
                <td style="padding:8px;">${r.brand_name || "-"}</td>
                <td style="padding:8px;max-width:280px;word-break:break-all;">${hasWebsite
                    ? `<a href="${r.website}" target="_blank" rel="noopener">${r.website}</a>`
                    : '<span style="color:var(--text-secondary)">未找到</span>'}</td>
                <td style="padding:8px;max-width:400px;font-size:14px;">${r.description || "-"}</td>
            </tr></tbody>
        </table>
        <p style="color:var(--text-secondary);font-size:12px;margin-top:4px;">数据来源: ${sourceLabel}</p>
    `;
    }

    function renderBrandAnalysisReport(data) {
        if (!data || !data.results || data.results.length === 0) {
            return '<p style="color:var(--text-secondary)">暂无分析结果。</p>';
        }

        let html = "";
        if (data.brand) {
            html += `<p style="margin-bottom:16px;color:var(--text-secondary);">品牌: <strong>${data.brand}</strong> &nbsp; Task ID: ${data.task_id || "-"}</p>`;
        }

        const levels = [1, 2, 3];
        for (const level of levels) {
            const items = data.results.filter((r) => {
                const cfg = PLATFORM_ANALYSIS_CONFIG[r.platform];
                return cfg && cfg.level === level;
            });
            if (items.length === 0) continue;

            html += `<div style="margin-top:20px;margin-bottom:8px;padding:6px 12px;background:rgba(255,255,255,0.05);border-radius:6px;font-weight:600;color:var(--text-secondary);font-size:14px;">${SOURCE_LEVEL_LABELS[level]}</div>`;

            for (const r of items) {
                const cfg = PLATFORM_ANALYSIS_CONFIG[r.platform];
                if (cfg.kind === "brand-website") html += renderBrandWebsite(r, cfg);
                else if (cfg.kind === "users-table") html += renderAnalysisUsersTable(r, cfg);
                else if (cfg.kind === "score-row") html += renderAnalysisScoreRow(r, cfg);
                else if (cfg.kind === "shop-row") html += renderAnalysisShopRow(r, cfg);
            }
        }

        return html;
    }

    window.renderBrandAnalysisReport = renderBrandAnalysisReport;
})();
