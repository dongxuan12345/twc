# AGENTS.md —— 开发规则与 AI 协作边界

> 本文件是**给 AI 编程助手看的项目规约**，也是作业要求的「AI 协作边界记录」。
> 任何人（或任何模型）在本仓库改代码前，必须先读这一页。
> 违反下列规则产生的提交，一律视为无效提交。

---

## 1. 项目一句话

面向**神经网络**这一科研大方向的文献追踪看板：按「功能方向」从 arXiv 拉取近 X 天的新论文，
交给大模型提炼成【一句话核心贡献】【数据集/方法】【代码是否开源】三个结构化标签，
再用 Streamlit 渲染成可搜索、可按开源状态筛选的网页。

## 2. 技术栈边界（不要擅自替换）

| 层 | 选型 | 说明 |
|---|---|---|
| 前端 | **Streamlit** | 唯一入口 `app.py`，不引入 React/Vue |
| 数据源 | **arXiv Atom API** | 唯一外部数据源；不爬 HTML 页面 |
| LLM | **DeepSeek（OpenAI 兼容协议）** | 通过 `openai` SDK 调用，模型名走配置 |
| 存储 | **SQLite**（标准库 `sqlite3`） | 不引入 ORM、不引入外部数据库 |
| 依赖 | `requirements.txt` 里的 5 个包 | 新增依赖必须在 PR 说明理由 |

---

## 3. AI 协作边界（核心）

### 3.1 允许 AI 全权完成的部分

- 样板代码：Streamlit 布局、表格渲染、参数表单
- 文档初稿：PRD/TDD 的结构化骨架、README
- 单元测试的用例枚举
- 代码格式整理、注释补全、类型标注补全
- 报错信息的措辞优化

### 3.2 AI 产出后**必须人工复核**的部分

| 部分 | 复核动作 | 复核人 |
|---|---|---|
| arXiv `search_query` 语法 | 打开浏览器跑一遍该 URL，确认返回 `<entry>` 而非错误页 | 本人 |
| 日期区间换算（UTC / 本地时区） | 手工算一次 `submittedDate` 边界，与代码输出比对 | 本人 |
| **LLM Prompt 的字段定义** | 逐句确认「禁止猜测」「没写就填 null」等约束没有被改写弱化 | 本人 |
| JSON 降级逻辑 | 手动构造非法 JSON 输入，确认走 fallback 而不是崩溃 | 本人 |
| 数据库 schema | 确认主键能去重、`arxiv_id` 带版本号已剥离 | 本人 |
| 所有涉及金额/配额的地方 | 估算 token 成本，确认有缓存 | 本人 |

### 3.3 明令禁止 AI 做的事

1. **禁止编造 API 字段**。任何 `paper.xxx` 属性必须能在真实的 arXiv XML 里找到对应节点，
   或能在本项目 `src/arxiv_client.py::Paper` 里找到定义。不确定就先打印原始 XML。
2. **禁止编造评测数字**。文档里不允许出现「提升 30%」「准确率 92%」这类未经测量的指标。
3. **禁止在代码里写死任何密钥**。见第 5 节红线。
4. **禁止为了跑通而吞异常**。`except Exception: pass` 一律不收；至少要 `logger.warning` 并记录上下文。
5. **禁止删除或弱化防幻觉校验**（`code_url` 必须能在原文中溯源、三态降级逻辑），
   即使它会让某些论文显示为 `unknown`。
6. **禁止伪造 `progress.md` 的时间线**。日志只能追加，不能回填。

### 3.4 Prompt 使用记录（每次与 AI 协作的留痕）

> **使用方式**：每完成一次「让 AI 写 → 自己改 → 验证」的循环，就在这里追加一行。
> 日期必须真实，不得回填或预设。下表目前只有一条真实记录。

| 日期 | 用途 | AI 产出 | 我的改动 |
|---|---|---|---|
| 2026-11-23 | 按 PRD/TDD 生成项目骨架（config / categories / arxiv_client / llm_extractor / storage / pipeline / app）与四份文档初稿 | 全部模块初版代码 | 待逐项复核：① 浏览器实跑 `search_query` ② 手工核对 `submittedDate` 边界 ③ 构造非法 JSON 验证降级 ④ 用真实 Key 跑通 3 篇 |

---

## 4. 代码规范

- **Python 3.10+**，全部文件首行 `# -*- coding: utf-8 -*-`，模块级 docstring 必填。
- 类型标注：公开函数必须有参数与返回值标注。
- 命名：`snake_case` 函数/变量，`PascalCase` 类，常量 `UPPER_SNAKE`。
- 注释写「**为什么**」，不写「是什么」。禁止 `i += 1  # i 加一`。
- 单个函数不超过 60 行；超过就拆。
- 所有网络请求必须带 `timeout`；所有写库操作必须在事务内。
- 日志用 `logging`，禁止 `print`（`pipeline._main` 的 CLI 输出除外）。
- **界面文案禁止硬编码**：一律写进 `src/i18n.py`，`app.py` 里只能通过 `t(lang, key)` 取。
  新增文案必须同时补 `zh` 与 `en` 两份，否则 `tests/smoke_test.py` 的 key 对齐用例会失败。
- **翻译/LLM 调用必须可缓存**：摘要译文存 `translations` 表，检索词译文存 `keyword_cache` 表，
  禁止在渲染路径上无缓存地反复调用模型。

### 提交信息格式

```
<type>(<scope>): <subject>

type:  feat | fix | docs | refactor | test | chore
scope: arxiv | llm | ui | db | docs
```

示例：`feat(llm): 增加 JSON 解析失败后的修复重试`

---

## 5. 安全红线（违反直接判负）

1. **密钥只能存在于 `.env`**，仓库里任何文件都不允许出现真实 Key。
   - 代码中统一写 `os.getenv("DEEPSEEK_API_KEY", "Your Key")` 或 `config.py` 里的常量。
   - `.env` 已在 `.gitignore` 第一段被忽略，**不得删除该规则**。
2. 仓库必须提供 `.env.example`，内容只含占位符。
3. 提交前自检：
   ```powershell
   git log -p | Select-String -Pattern "sk-|DEEPSEEK_API_KEY\s*=\s*[\"']sk"
   ```
   有命中说明历史里带 Key，必须改 Key 并用 `git filter-repo` 清理历史。
4. 日志与界面上展示的 Key 必须脱敏（见 `config.masked_key()`）。

---

## 6. 每次改动后的必做验证

```powershell
# 1) 静态可导入（不需要网络、不需要 Key）
python -c "import src.pipeline, src.storage, src.llm_extractor, src.translator, src.i18n; print('ok')"

# 2) 纯离线单测：JSON 容错解析 + 字段归一化 + i18n 对齐 + 中文词典翻译
python tests/smoke_test.py

# 3) 只抓取不调 LLM，验证 arXiv 链路（约 10 秒）
python -m src.pipeline --category cnn_vision --days 7 --max 5 --no-llm

# 4) 完整链路（需要 Key）
python -m src.pipeline --category transformer_llm --days 7 --max 3

# 5) 界面
streamlit run app.py
```

第 1、2 步必须在每次提交前跑通；任何一步失败都不允许提交。

---

## 7. 目录约定

```
your_project_root/
├── AGENTS.md            # 本文件
├── 研究说明.md           # Milestone 1：PRD
├── 技术设计文档.md        # Milestone 2：TDD
├── progress.md          # Milestone 3：进展日志（只追加）
├── app.py               # Streamlit 入口
├── requirements.txt
├── src/
│   ├── config.py        # 配置与密钥读取
│   ├── categories.py    # 神经网络功能方向分类表
│   ├── i18n.py          # 界面文案中英双语表（默认中文）
│   ├── arxiv_client.py  # 抓取 + 解析 + 重试
│   ├── llm_extractor.py # Prompt + 容错解析 + 防幻觉
│   ├── translator.py    # 摘要多语言翻译 + 中文检索词英译
│   ├── storage.py       # SQLite 读写
│   └── pipeline.py      # 编排 + CLI
├── tests/smoke_test.py  # 纯离线冒烟测试
├── preview.html         # 静态界面预览（非交付必需，可删）
├── data/                # 运行时生成，已 gitignore
└── logs/                # 运行时生成，已 gitignore
```

---

## 8. 给 AI 的验收自问清单

在声称「做完了」之前，逐条自答：

- [ ] 我提到的每个函数/字段，都在仓库里真实存在吗？
- [ ] 我是否在没有证据的情况下，声称某段代码「已经测试通过」？
- [ ] 我有没有改动密钥相关的代码？有没有把 Key 写进示例？
- [ ] 我改的逻辑，是否会影响 JSON 降级或防幻觉校验？影响的话重跑 `tests/smoke_test.py` 了吗？
- [ ] 文档里新增的描述，和 `src/` 里的实现一致吗？
