# GEO 信源检测系统

多平台品牌账号 / 官网检测终端：FastAPI 后端 + Electron 壳 + CloakBrowser。

## 启动

开发环境（Python 后端）：

```powershell
python main.py
```

浏览器打开：http://127.0.0.1:8000

Electron 桌面端：

```powershell
npm install
npm start
```

## 目录

| 路径 | 说明 |
|------|------|
| `main.py` | 后端入口（uvicorn） |
| `config.py` | 全局配置与平台开关 |
| `core/` | 检测编排、忙锁、官网查询、浏览器管理 |
| `core/web_engines/` | 百度 / Bing / 博查搜索适配器 |
| `platforms/` | 各站点爬虫适配器 |
| `web/` | FastAPI 页面与静态资源 |
| `tests/` | pytest 单测 |
| `data/` | 本地数据（cookies / tasks / results，默认不入库） |

## 配置

1. 复制 `config/packaged.env.example` 为本地配置参考  
2. 开发可用项目根目录 `.env`；打包后用户配置在 `%APPDATA%/detection/.env`  
3. 常用项：`LLM_API_KEY`、`BOCHA_API_KEY`、`BING_API_KEY`、Kafka / 消费轮询相关变量  

敏感文件（`.env`、`config/packaged.env`、cookies）已在 `.gitignore` 中忽略。

## 测试

```powershell
python -m pytest tests/ -q
```
