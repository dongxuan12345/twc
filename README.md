# NN Lit Radar · 神经网络领域 AI 文献追踪看板

> **作业三：科研领域 AI 文献追踪看板**
> 领域：**神经网络**（按功能切分为 13 个子方向：视觉 / 大模型 / 图网络 / 生成模型 / 强化学习 / PINN / 理论 / 时序 / 多模态 / 高效推理 / NAS / 脉冲网络 / 语音）。
> 自动检索真实论文 → 大模型结构化提取（带证据校验与降级）→ 可视化看板 → 错误兜底。

- 数据全部来自**真实公开 API**（arXiv / OpenAlex），不编造文献。
- **两套前端**：`index.html` 双击即用（纯前端，无需安装）；`app.py` Streamlit 版（功能最全，含多语言摘要翻译）。
- 中文关键词自动英译、标题与核心贡献中文化、深浅色三态主题、CSV 导出。
- 大模型环节有 **JSON 解析容错 → 修复重试 → 规则降级** 三级兜底，任何单点失败都不会让页面白屏。

**作业要求 → 实现映射**

| 作业 MVP 模块 | 实现位置 | 说明 |
|---|---|---|
| ① 自动检索（窗口 X 天） | `src/arxiv_client.py`、`src/pipeline.py`、`index.html` | arXiv Atom API + OpenAlex；时间窗口以「年」为单位可填小数（0.5 / 0.6 / 1.5），换算成 UTC 的 `submittedDate` 绝对区间 |
| ② LLM 结构化提取 | `src/llm_extractor.py`、`index.html` 的 `LLM_SYSTEM` | DeepSeek `deepseek-chat`；few-shot + `response_format=json_object` + `temperature=0`；输出【一句话核心贡献】【数据集/方法】【代码是否开源】 |
| ③ 可视化看板 | `app.py`（Streamlit）、`index.html`（原生单页） | 关键词搜索、开源状态筛选、方向筛选、扁平结果列表、CSV 导出 |
| ④ 防幻觉与错误兜底 | `src/llm_extractor.py`、`src/arxiv_client.py`、`src/storage.py` | 三级 JSON 容错、修复重试、降级保原文、链接溯源校验、开源三态降级、指数退避重试、抓取审计 |
| 文档要求 | `AGENTS.md`、`研究说明.md`、`技术设计文档.md`、`progress.md` | PRD / TDD（含 Mermaid 架构图）/ 进展日志 / AI 协作边界 |

---

## 1. 两种运行方式

### 方式 A：双击即用（零安装）

双击 **`index.html`**，浏览器打开就是一个完整看板：

- 实时检索 **OpenAlex**（官方支持浏览器跨域），失败自动降级到 **arXiv + 公共 CORS 代理**
- 侧边栏可填 DeepSeek API Key（只存本机 `localStorage`，**不写入任何文件、不上传**），填了就调用大模型做结构化提取；不填则用本地规则
- 结果按「英文标题 + 中文标题 / 中文核心贡献 / 数据集标签 / 开源状态」扁平展示
- 数据存 `localStorage`，刷新不丢；支持 CSV 导出、深浅色主题、中英界面

> 浏览器版不落库、不带多语言摘要翻译——那是 Streamlit 版的职责。

### 方式 B：Streamlit 后端版（功能最全）

环境：Python 3.9+（本项目在 Python 3.9 / Windows 11 验证语法兼容；无 3.10+ 语法依赖）。

```powershell
cd F:\作业三
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # 编辑 .env 填入 DEEPSEEK_API_KEY
streamlit run app.py
```

打开 <http://localhost:8501>。

或者直接双击 `启动看板.bat`（自动找 Python、建虚拟环境、装依赖、起服务）。

**验证后端链路（不花 token）**：

```powershell
python -m src.pipeline --category cnn_vision --days 7 --max 5 --no-llm
python -m src.pipeline -c transformer_llm -c gnn -d 3 -m 10
```

---

## 2. 环境变量（`.env`）

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | 否 | 占位符 `Your Key` | 配置后启用 LLM 提取与摘要翻译；缺失时自动降级为规则抽取并在界面提示 |
| `DEEPSEEK_BASE_URL` | 否 | `https://api.deepseek.com` | 换 OpenAI 兼容服务时改这里 |
| `DEEPSEEK_MODEL` | 否 | `deepseek-chat` | 模型名 |
| `LLM_TIMEOUT` / `LLM_MAX_RETRIES` | 否 | `120` / `3` | 单次超时与重试次数 |
| `ARXIV_MIN_INTERVAL` | 否 | `3.0` | arXiv 请求最小间隔（官方建议 ≥3s，调小会封 IP） |
| `ARXIV_MAX_RETRIES` / `HTTP_TIMEOUT` | 否 | `3` / `30` | 抓取重试与超时 |

> 云端部署（Streamlit Community Cloud）时，`src/config.py` 会先读环境变量，读不到再读 `st.secrets`，两种方式都支持。

---

## 3. 数据源与限流

| 源 | 鉴权 | 用途 | 策略 |
|---|---|---|---|
| arXiv Atom API | 免 Key | 预印本，按 `cat:` + `submittedDate` 检索 | 请求间隔 ≥3s；429/5xx 指数退避（2→4→8s）；4xx 立即失败并提示 |
| OpenAlex | 免 Key | 浏览器版主数据源（官方支持 CORS）；摘要以倒排索引返回，本地还原 | `has_abstract:true` 优先，无摘要结果直接剔除；失败回退 arXiv |
| 公共 CORS 代理（allorigins / codetabs / corsproxy） | 免 Key | 浏览器直连 arXiv 被拦时的兜底 | 仅浏览器版使用；三级依次尝试，全失败则回退本地示例数据 |

> 浏览器版**必须**走 OpenAlex 为主：arXiv 不返回 CORS 头，公共代理经常限流或收费（会返回 401/403）。

---

## 4. 防幻觉与错误兜底（模块④设计）

1. **输出强约束**：`response_format={"type":"json_object"}` + `temperature=0` + 固定字段 schema + 3 组 few-shot（覆盖开源 yes / unknown / no 三态）。
2. **三级 JSON 容错**：剥离 ``` 代码围栏 → 括号配对扫描（跳过字符串内的花括号）→ 去除尾逗号；仍失败则抛 `JSONParseError`。
3. **修复重试**：把非法输出回灌给模型 + 追加修复指令，重试 1 次；`parse_status` 记为 `repaired`。
4. **降级不崩**：两次都失败时 `parse_status="fallback"`，保留英文原文照常展示，卡片标注 ⚠️，不阻塞其余论文。
5. **防幻觉校验**：模型给出的 `code_url` 必须能在摘要 / comment 原文中找到（归一化比对），否则丢弃；说"开源"却拿不出链接则降级为 `unknown`；一句话贡献为空视为抽取失败。
6. **网络兜底**：超时 / 429 / 5xx 指数退避重试；单方向失败记入 `stats.errors` 与 `fetch_log` 表，其它方向继续。
7. **增量与缓存**：已成功结构化的论文不重复调用（`has_extraction`）；译文按 `(arxiv_id, target_lang)` 缓存，检索词译文按 `src` 缓存。

降级状态机：

```text
CallLLM → ParseJSON → Validate → Accept        (parse_status = ok / repaired)
                 ↓ 失败                ↓ 两次失败
            修复重试 1 次 ────────→ 降级 fallback（保留原文）
   API 异常 ──→ 退避重试 3 次 ──→ failed（下次刷新重试）
```

---

## 5. 功能一览

| 功能 | 浏览器版 `index.html` | 后端版 `app.py` |
|---|---|---|
| 13 个神经网络功能方向 | ✅ | ✅ |
| 自定义主题词（可多个，中文自动英译） | ✅ | ✅ |
| 研究范式（实验 / 机理模型 / 预测模型） | ✅ | — |
| 时间窗口（年，支持 0.5 / 0.6 小数） | ✅ | ✅ |
| LLM 结构化提取 | ✅（页面内填 Key） | ✅（`.env`） |
| 摘要多语言翻译（8 种语言） | — | ✅ |
| 中文标题 / 中文核心贡献 | ✅（LLM 或翻译接口） | ✅（LLM 或翻译接口） |
| 关键词搜索 + 开源状态筛选 | ✅ | ✅ |
| 深浅色 / 跟随系统主题 | ✅ | ✅ |
| CSV 导出 | ✅ | ✅（选了翻译语言时附译文列） |
| 数据持久化 | localStorage | SQLite（6 张表） |

---

## 6. 目录结构

```text
nn-lit-radar/
├─ index.html               # 浏览器版看板（双击即用）
├─ app.py                   # Streamlit 版看板（功能最全）
├─ requirements.txt
├─ .env.example             # 密钥模板（真实 .env 不入库）
├─ .gitignore
├─ src/
│  ├─ config.py             # 配置与密钥读取（env → st.secrets）
│  ├─ categories.py         # 13 个功能方向检索配方
│  ├─ i18n.py               # 界面文案中英双语表（默认中文）
│  ├─ arxiv_client.py       # 检索式构造 / 限流 / 退避 / Atom 解析
│  ├─ llm_extractor.py      # Prompt + 三级容错 + 防幻觉校验
│  ├─ translator.py         # 摘要多语言翻译 + 中文检索词英译
│  ├─ storage.py            # SQLite：papers / paper_groups / extractions / fetch_log / translations / keyword_cache
│  └─ pipeline.py           # 抓取→精筛→入库→抽取 编排 + CLI
├─ tests/
│  └─ smoke_test.py         # 25 个纯离线用例（不联网、不调模型）
├─ 启动看板.bat / launch.ps1 # Windows 一键启动
├─ 打开预览.html             # 带时间戳的入口页（绕开浏览器缓存）
└─ 文档：AGENTS.md / 研究说明.md / 技术设计文档.md / progress.md / 提交说明.md
```

---

## 7. 测试

```powershell
python tests/smoke_test.py
```

覆盖 25 个纯离线用例，不需要网络、不需要 Key：

- 检索式与时间窗口换算（UTC 边界、小数年折算）
- Atom 字段清洗（`arxiv_id` 去版本号、时间统一为 `YYYY-MM-DDTHH:MM:SSZ`）
- JSON 容错解析（代码块 / 前置废话 / 尾逗号 / 字符串内花括号 / 完全非法）
- 字段归一化与防幻觉（开源三态、数据集清洗、链接溯源）
- i18n 中英 key 对齐（防漏译）与回退链
- 中文检索词词典翻译（不触发任何网络请求）

后端链路另有可复跑的人工验收清单，见 `progress.md` 的「待验证」小节。

---

## 8. 界面预览

> 截图请放到 `docs/screenshots/` 后取消下面注释；未放截图时 GitHub 上不会显示破图。

<!--
![浏览器版看板](docs/screenshots/index-1440.png)
![Streamlit 版看板](docs/screenshots/streamlit-1440.png)
![证据与摘要展开](docs/screenshots/evidence.png)
-->

---

## 9. 已知限制

- **浏览器版的 LLM 调用依赖服务端 CORS**。DeepSeek 目前允许浏览器直连（已实测），若未来关闭，页面会自动回退本地规则并在顶部横幅提示原因。
- **浏览器版不落库**：数据在 `localStorage`，换浏览器 / 清缓存会丢；正式使用请用 Streamlit 版。
- **摘要缺失的文献无法抽取**（OpenAlex 部分出版社不提供摘要），这类记录会被直接剔除而不是显示「未提取到」。
- **`code_open_source` 以摘要为准**：只在正文里给仓库链接的论文会被判为 `unknown`——这是有意的取舍，宁缺毋滥。
- **单机 SQLite + 无并发保护**：同时点两次刷新可能重复抓取；生产环境需要加锁。
- **翻译走公共接口**：浏览器版的中文标题 / 贡献翻译使用 MyMemory 免费接口，有速率限制，失败时保留英文。

---

## 10. 数据与学术诚信

- 所有论文标题、作者、摘要、链接均来自 arXiv / OpenAlex 官方 API，**不生成不存在的文献、作者或数字**。
- 大模型只做「摘要 → 结构化字段」的信息抽取，`evidence` 字段保留支撑结论的英文原句，可回溯核对。
- 示例数据（`index.html` 内置的 8 条）仅用于**断网演示**，已明确标注为「示例数据」，不代表真实文献。
- 遵循各数据源使用条款：arXiv 请求间隔 ≥3s、不抓取 PDF 全文。

---

## 11. 安全说明

- 仓库中**不含任何真实密钥**，代码里只出现占位符 `"Your Key"`。
- `.env` 与浏览器版的 `llm-key.local.js` 均已被 `.gitignore` 忽略。
- 界面上展示的 Key 一律脱敏（`sk-b2****fbeb1`）。

> **上传 GitHub 前必读**：`git push` / GitHub Desktop 会遵守 `.gitignore`；
> **GitHub 网页版「拖拽上传」不认 `.gitignore`**，会把这些文件一起传上去。
> 用网页上传时请先删除 `.env`，详见 [提交说明.md](提交说明.md)。

---

## 12. 变更记录

| 版本 | 内容 |
|---|---|
| v1.0 | MVP：13 方向检索 + LLM 结构化 + Streamlit 看板 + 兜底 |
| v1.1 | 摘要 8 语言翻译、中文检索词自动英译、界面中英双语 |
| v1.2 | 自定义主题词、显式搜索按钮、三态主题、语言按钮化 |
| v1.3 | 时间窗口改「年」（支持 0.5 小数）、结果改扁平列表 |
| v1.4 | 新增纯前端版 `index.html`（OpenAlex 数据源）、视觉重做 |
| v1.5 | 浏览器版接入大模型（页面内填 Key）、中文标题与中文核心贡献 |
