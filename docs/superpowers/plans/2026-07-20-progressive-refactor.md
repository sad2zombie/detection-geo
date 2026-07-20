# Progressive Refactor Implementation Plan

> **For agentic workers:** Execute task-by-task. Behavior must stay identical.

**Goal:** Improve maintainability via incremental extraction without changing detect/search/Kafka behavior.

**Architecture:** Horizontal foundation first — public result helpers + pure brand-match functions + unit tests — then later split orchestration/guards and brand/web search pipelines.

**Tech Stack:** Python 3.12, pytest, existing FastAPI/CloakBrowser stack (untouched this wave).

## Global Constraints

- No intentional behavior or API contract changes
- Prefer move/re-export over rewrite
- Do not commit unless user asks
- Minimum change: only touch files needed for the current wave

---

## Wave 1 — Foundation (this plan)

### Files

| File | Action |
|------|--------|
| `core/detect_result.py` | **Create** — `wrap_platform_result`, `format_detect_errors`, `baidu_score_str`, `empty_platform_result` |
| `core/brand_match.py` | **Create** — follower parse, similarity, sort key, platform preprocess, `analyze_brand_result` |
| `core/search_engine.py` | **Edit** — import from new modules; keep orchestration/caches/busy lock |
| `core/kafka_producer.py` | **Edit** — use public `detect_result` API |
| `tests/test_detect_result.py` | **Create** |
| `tests/test_brand_match.py` | **Create** |

### Tasks

- [x] Task 1: Add failing tests for detect_result + brand_match expected behavior (copied from current logic)
- [x] Task 2: Implement `core/detect_result.py` and `core/brand_match.py` by moving code as-is
- [x] Task 3: Wire `search_engine` / `kafka_producer` to new modules
- [x] Task 4: Run `pytest` — all green (`12 passed`)

### Later waves

- [x] Wave 2: `detect_guard.py` + thin re-export from `search_engine`（compat imports 保留）
- [x] Wave 3: split `brand_search` / `web_search`
- [x] Wave 4: task field cleanup, empty packages, README

### Wave 3 notes

- `core/web_engines/`：`baidu` / `bing` / `bocha` / `common`；`web_search.py` 仅保留降级编排
- `core/brand_rules.py`：官网规则识别与合成
- `core/brand_llm.py`：大模型查询
- `core/brand_search.py`：流水线入口 + 缓存；对外 API 不变（`search_brand` / `get_cached_brand_result` / `SOURCE_LLM`）
- 模块注释与实现对齐：大模型优先，再搜索平台

### Wave 4 notes

- `task_manager`：统一写入 `platform` 列表；读时兼容历史 `platforms`；`get_task` / `_write_task` 规范化
- 删除空包 `ai/`、`utils/`
- 新增根目录 `README.md`
