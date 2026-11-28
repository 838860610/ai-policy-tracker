# 更新日志

本项目的所有重要变更都记录在此文件。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

- `Added` 新增功能
- `Changed` 变更/改进
- `Fixed` 修复问题
- `Removed` 移除内容

## [Unreleased]

### Added

- **数据结构化与机器可读 API（/api/v1）**：新增 `scripts/gen_api.py` 生成 `site/generated/api/v1/{products,summary}.json` 只读 API——全量政策数据 + 风险/训练状态汇总，`schema_version` 固定 "1.0"（承诺只增字段不删字段不改语义），`generated_at` 取数据内最新核实日期保证输出确定性；外部可直接把本项目当数据源引用，CI 接入生成与 `--check`
- **risk_level 推导交叉校验 + criteria 显式化**：新增共享推导模块 `scripts/policy_logic.py`（唯一权威实现），`infer_training_status` 从 gen_data_bundle / gen_readme_table / validate_data 三份副本收编；绿色标准核对与**红色条件交叉校验**（训练且未明示退出机制、训练场景下未去标识化——命中却未标红则提示，可写 `risk_override_reason` 说明分歧）。联系式退出在既有校准里黄/红先例并存（keling/tongyi/xunfei/qoder 黄 vs codebuddy 红），不做机械判定。新增 `criteria` 字段（绿色③④留存/版权的显式布尔判定）随迁移全量填写（63/63），前端推导卡与校验脚本统一读显式值
- **training_status 全量显式化**：一次性迁移把 48 个依赖启发式推断的版本写回显式 `training_status`（值来自推导函数，与 bundle 输出零变化，语义对比确认），前端 detail.js 的推断逻辑降级为兜底；新增回归测试锁定"显式值 == 推导值"不变量
- **tiangong 个人版保留黄色的推导分歧记录**：`tiangong:toc` 命中红色③（训练实质 + 未去标识化）但按既有口径保留黄色——训练判定为"优化/改进"的实质推断（原文无明示训练授权专条）且存在一般性撤回权；已写 `risk_override_reason` 说明分歧依据，**待人工复核**：若后续条款出现明示训练授权应改判红色
- **"核实即入 timeline"制度化**：`policy-change-verify` SKILL.md 与 `policy_schema.md` 把 timeline 从"里程碑变化可选追加"改为**实质性变更强制条目**（`--resolve` 收尾前自查已补）——timeline 是详情页时间线与订阅 feed 的变更叙事主线，实质变更只记在 CHANGELOG 里等于"追踪器没有追踪"。event 写条款实质（哪条从什么改成什么），核实过程仍归 `verification_notes`
- **Kimi timeline 补录**：2026-08-31 生效协议的关键变化此前只散落在 description/key_findings——现行协议授予免费使用权将输入输出用于'模型服务优化'（默认开启，退出需联系 support@moonshot.cn）、2025 年旧版'全球、永久、可转让、品牌推广'授权表述已移除（2026-08-30 复核确认）。扫描确认其余无 timeline 产品的记录均为当前状态描述而非未收录的变更，无需补录
- **变更订阅与通知闭环（RSS + webhook + diff 公开展示）**：此前检测到变更只有 Actions 日志一行，"最后一公里"全靠人主动打开站点。新增三件套：
  - `scripts/gen_feed.py` 生成 Atom 订阅源 `site/feed.xml`（timeline 人工核实记录 + 待核实队列按时间倒序合并，最多 60 条；待核实条目带快照 diff 片段，entry id 绑定首次检测时间避免每轮重复推送）。首页 head 与页脚加发现链接，ci.yml / monitor.yml 接入生成与 `--check`
  - 监控检测到 changed 时 `update_pending_verification` 用快照 prev→latest 生成截断的统一 diff 写入待核实队列（`diff_preview` 字段，difflib 纯标准库）；详情页新增"⚠️ 检测到待核实的政策变更"卡片渲染该 diff（队列无该产品时隐藏），资源版本号升至 `20261118-2`
  - `scripts/notify_webhook.py` 支持飞书 / 钉钉 / Telegram / 通用 JSON 四种 payload，monitor.yml 在监控轮后调用（Secrets `MONITOR_WEBHOOK_URL` + Variables `MONITOR_WEBHOOK_TYPE` 配置后生效，未配置静默跳过；continue-on-error 保证通知故障不掩盖监控结果）。对外文档 `site/docs/update-monitoring.md` 新增"订阅变更动态"章节
- **产品独立静态详情页**：新增 `scripts/gen_product_pages.py`，以 `site/detail.html` 为模板生成 48 个 `site/p/{id}.html`，每个页面有独立 `title`、描述、`og:title/description/url`、`twitter` 卡片与 `canonical`，并写入静态 `<noscript>` 摘要；`site/sitemap.xml` 改由同一脚本生成。首页所有详情链接切到 `p/{id}.html`，旧 `detail.html?id=` 入口继续可用
- **详情页站内导航与版本深链**：同厂商其他产品、按列表顺序的上一个/下一个；`?tab=toc|tob` 可直接打开指定版本，切换标签时同步地址栏
- **明亮主题**：新增 `site/js/theme.js` 与顶栏/详情页/文档页的主题切换按钮，选择写入 `localStorage` 并在样式表加载前应用，避免亮色用户看到黑屏闪烁；亮色 token 重新校准了正文、风险信号色与边框的对比度。**默认使用明亮主题**，只有用户显式选择过暗色才保持暗色
- **抓取健康队列**：新增 `site/generated/monitor_health.json`，与"政策变化待核实队列"分离。每轮由 `update_status.json` 完全重建，记录 `health`、失败原因、连续不健康轮次与建议动作；目标恢复后条目自动消失
- **目标级抓取配置**：`versions.*` 与 `sources[]` 条目支持 `fetch_method`、`content_selector`、`wait_for_selector`、`min_body_chars`，不必为一个站点把整产品都切成浏览器抓取；`--no-browser` 现在只跳过 `browser` 目标
- **局部重试**：`check_updates.py` 新增 `--products`、`--only <pid>:<key>`、`--no-prune`，只重跑选中目标、其余继承上次状态（`meta.partial_run`），修完抓取配置后无需重跑全量
- **首页抓取降级明细**：banner 下方可展开"抓取降级明细"，逐条列出产品、目标、健康类型、失败原因与上次成功抓取时间；`monitor_health.json` 缺失时从状态里的 `health` 兜底推导
- `tests/test_scripts.py` 新增 48 项（54 → 91）：`TestFetchHealth`、`TestMonitorHealthQueue`、`TestPartialRetry` 三个新类共 32 项，另在既有类中补 16 项回归（待核实队列入参形状、`--only` 真正筛选、快照不被误删、重试预算、`last_good_at` 回填、健康队列与状态一致性、首页健康明细渲染）。新增真实失败页样本 `tests/fixtures/empty_shell.html`、`render_required_shell.html`，区分 `empty_body` / `render_required`

### Changed

- **核实 2026-11-23 监控轮 6 项待变更**：WorkBuddy 补充服务协议9.2(9)反代理/凭证复用等行为限制；Qoder CN 设备信息新增GAID；Trae企业版接入豆包飞书账号并新增账号/开通/资源/消耗数据同步；Gemini个人版调整保留期限、拆分对话与音频训练控制并披露远程任务/短信删除例外；MiniMax海螺新版补充性别/网络类型收集、训练撤回渠道与未成年人规则；豆包企业版条款未变按噪声resolve，个人版同步补充媒体读取与应用安装列表披露
- **测试补盲区（141 → 150）**：`fetch_with_retry` 内部重试策略此前被整体 mock 零覆盖——新增 429 + Retry-After、429 无头退避序列、非 429 不重试、网络错误线性退避序列、重定向逐跳 SSRF 复检 5 项；另补 `prune_dated` 存档裁剪、prune 读取失败保护、时间戳带时区、失败原因结构化归纳 4 项
- **条款提取工具支持英文政策页**：`extract_clauses.py` 原关键词全中文，对 ChatGPT/Claude/Gemini 英文原文快照全部零命中；补英文训练/退出/留存同义词组（项目对部分海外产品锁定 hl=zh-CN，两组都跑）
- **移除 `app.js` 死代码**：文件内重复定义的 `vendorOf()` 引用了 common.js IIFE 内未导出的 `VENDOR_RULES`（若被调用即 ReferenceError），靠函数提升 + 13 行赋值覆盖才没生效；删除后统一走 `PT.vendorOf`。资源版本号 `?v=` 同步升到 `20261118-1`
- **核实 2026-11-14 手动监控轮 8 项待核实并清零**：`glm-coding-plan` 2026-11-13 版订阅协议为实质性收紧——新增'单次购买套餐特别条款'专章（额度到期失效不退还、禁标准 API 调用、违规转售 5 倍违约金）、责任限额由'最近一个自然月消费总额'收窄至'引发责任的单产品实际消耗费用（不含赠送/优惠券/预付未消耗）'，训练维度未变（bigmodel 匿名化训练条款零变化，维持 red）；`qwenwork`（帮助页导航链接）、`gemini:tob`（翻译措辞统一）、`kimi` main/tob 与 `bigmodel` 与 `glm-coding-plan:tob`（零宽字符清理，全部条款零变化）、`workbuddy`（新增'电脑操控/跨设备数据迁移'功能权限披露，训练/留存条款零变化）确认为非条款变化。8 项目标全部 `--resolve`，`workbuddy` 推荐语同步最新指引版本日期
- **核实并更新 6 个产品数据（2026-11-09 监控轮 9 项待核实清零）**：`tencent-yuanbao` 训练模式翻转为退出式——2026-10-29 版协议（2026-11-05 生效）默认授予许可用于'质量分析、模型训练和服务优化'，'体验优化计划'由加入开关变为关闭开关；风险按方法论校准后维持 yellow（默认训练但退出开关简单 + 明确去标识化，与 yuewen 同口径，未命中红色四条）；`autoclaw` 2026-10-27 版协议删除原'不可撤销、全球可分许可（含产品推广）'授权条款、新增团队服务数据用途限制，风险 red→yellow；`minimax` 开放平台主体更名'上海稀宇极智科技'（2026-11-13 生效，条款无实质变化）；`claude`（页面模板）、`gemini`（新功能披露）、`yuewen`（措辞微调）确认为非条款变化。9 项目标全部 `--resolve`
- **首页对比表合并为三列**：原「个人版训练 / 企业版训练 / 个人版风险 / 企业版风险」四列改为「个人版 / 企业版」两列，训练徽章与风险等级在同一单元格内并排展示（`.version-cell`），减少只占几个字符的风险列浪费的宽度；展开行 `colspan` 同步改为 3
- **风险等级完整文案**：表格风险由「🔴 高 / 🟡 中 / 🟢 低」改为「高风险 / 中风险 / 低风险」，并换成彩色圆点 + 轻量描边徽章的统一样式，避免 emoji 在不同平台宽度与基线不一致；筛选按钮同步使用完整文案
- **光晕性能降级**：移除首页 3 个 420–520px 光晕的 `filter: blur(120px)`（大半径模糊在移动端/低端 GPU 上持续合成），改用 `radial-gradient` 的天然柔边；≤768px 少画一层光晕，`prefers-reduced-motion` 下关闭顶栏与返回按钮的 `backdrop-filter`
- **首页展示优化**：压缩 Hero 与统计卡片、风险图例改为默认折叠的 `<details>`，1440×900 下表格从折叠线以下（920px）提前到 708px；窄屏把三组筛选改为单行横向滑动，表格改为卡片式（每个单元格带列名），375×812 下表格提前到 767px 且不再需要横向拖拽找风险列
- **首页核实日期改取数据最大值**：不再读 `products.json` 的 `meta.last_updated`（会停留在旧日期），改为取所有产品 `last_verified` 的最大值，并显示完整 `YYYY-MM-DD`；`gen_data_bundle.py` 白名单补 `last_verified`，否则首页取不到该字段
- **列表可用性**：新增“显示 X / 48 个产品”计数与无结果时的“清除全部筛选”按钮；厂商分组行可聚焦、可用 Enter/空格折叠并同步 `aria-expanded`；详情页 tabs 补 `role=tab/tablist/tabpanel`、`aria-selected` 与左右方向键切换
- **降噪与基线清理**：为 `qianfan`、`xunfei-api`、`skyproduction` 配置正文容器选择器（`.post__body` / `.content__default` / `.markdown-body`），为 `trae` 企业版补 `.topic-markdown`；同时把 `HASH_SCHEME` 升到 `text-v5`，让选择器变更后的首轮自动重建基线，不产生新的误报
- **核实并更新 12 个产品数据**：逐项比对 10-19 监控快照，确认 `gemini`、`bigmodel`、`qianfan`、`skyproduction`、`trae`、`xunfei-api` 等为非条款变化；更新 `ima`、`nano-ai`、`stepfun-api`、`workbuddy`、`minimax`、`yuewen` 的生效日期、条款摘录与说明，`last_verified` 统一为 2026-10-22，待核实队列清零
- **状态语义拆分**：目标与产品级结果新增 `health` 字段（`ok`/`initialized`/`rebaselined`/`degraded`/`no_baseline`/`blocked`）与 `last_good_at`、`health_reason`、`fetch_method`。首次建基线由 suspicious 改为 `ok` + `initialized`（不再算异常）；正文过短或抓取失败**不覆盖已有基线**，只标降级/无基线/被拦截；403/405/429/451 归为 `blocked`
- **修复待核实队列被静默清空**：`update_pending_verification` 期望 `{pid: info}` 映射，调用处却传了 `{"products": {...}}` 包装，导致每轮监控都把未解决的 `changed` 项当成"已移除目标"清空。补回归测试
- **修复 `--only` 未真正筛选**：`--only gemini:main` 过去会重跑全部 48 个产品（局部重试形同虚设）。现在只检查选中目标，其余继承上次状态
- **修复被跳过产品的快照被误删**：孤儿快照清理过去按"本轮状态里的 targets"判定活跃目标，`--no-browser` 跳过或 `monitor: false` 的产品会被当成已下线，快照目录（含 `latest.txt` / `prev.txt` / 日期存档）整片删除——快照是检测→核实回路唯一的持久历史。改为按**配置**（`policies/{id}.json` 展开的监控目标）判定；`--no-browser` 跳过整产品时改为沿用上次目标结果（标 `skipped_this_run`），不再抹掉 CI 建立的覆盖
- **目标级配置补齐 `main` 载体**：`main` 的 URL（`policy_url`）在顶层，天然没有内层对象可挂配置——此前"同一产品 main 需 browser、toc 是静态页"配不出来。新增 `targets.main`（只含 `main` 键；`toc`/`tob` 仍写 `versions.*`、补充来源仍写 `sources[]`，避免两处配置歧义），顶层字段继续生效，既有数据文件无需迁移。`validate_data.py` 抽出 `check_fetch_config()` 统一校验四处载体的 `fetch_method` 取值、选择器类型与正文下限类型，`targets.main` 额外检查拼写错误
- **本地专属监控（`monitor_scope: local`）**：新增目标级 `monitor_scope` 字段与 `--scope {all,ci,local}` 参数。用于 GitHub runner **连不上**的站点——`trae` 被 Cloudflare 拒绝数据中心 IP（`describe_shell()` 显示"实际拿到：空文档"，Chromium 根本没拿到响应 HTML），而同一 URL 在本地可正常抓到 12272 字符正文。现标记为 `local`，由 `./scripts/local_monitor.sh` 在本地跑并以本地结果为准；`monitor.yml` 改用 `--scope ci` 跳过它们
  - 被跳过的目标**沿用上次结果**（含快照引用与 `last_checked`）而非写成 `skipped`——否则监控覆盖率会在状态文件里缩水，快照还会被 `prune_orphan_snapshots` 当成"不再监控"删掉
  - 健康队列里这类目标的 `consecutive_runs` 与 `last_seen` 不因未检查而虚增，并标 `checked_this_run: false`；否则"每周查一次却从不上手"会让轮数一路涨到吓人
  - `local_monitor.sh` 只暂存并路径限定提交四个监控产物，不夹带其他已暂存改动；**不 push**（`git push origin main` 会触发 CI 与 Pages 真实发布，留给人工确认）
- **长文档站等待"内容不再增长"而非固定等待**：SPA 文档站分批注入正文，固定 `wait_for_timeout(600)` 会**稳定地**停在半截内容上——不再波动，却把不完整版本固化成基线，看起来"从未变化"实则漏掉后半段条款。新增 `wait_until_text_stable()`（连续两次采样增长不足 5% 才返回）与 `measure_rendered_text()`（按 `content_selector` 而非 `body` 测长度，避免侧栏展开导致 body 长而正文未填充完时选错渲染）
- **`content_selector` 命中多个时取文本最长的**：文档站选择器常同时命中正文容器与页脚/侧栏小容器，`select_one` 只取第一个会因 DOM 顺序变化抓到页脚（实测 `trae` 的 `[class*=content]` 命中 3 个 1.2 万字符正文容器 + 3 个 0～217 字符小容器）

### Fixed

- **本地监控不再污染 CI checked 状态**：`--scope local` 只更新 local 目标与 `meta.last_local_run`，非 local 目标保持最近 CI 的 checked 标记，`meta.last_run` 仍表示最近完整 CI 时间；页面把 local 目标显示为“由本地监控负责”，不再计作监控异常
- **Trae 本地源站验证与新政策回写**：本地可正常抓取 `trae:main`，已更新 2026-11-25 发布、2026-12-02 生效的个人版政策，补充豆包飞书统一账号、会员联动、TRAE宝云端同步及代码库索引上传说明
- **CI 支持手动触发**：`ci.yml` 增加 `workflow_dispatch`，除 PR 与 main push 外也可在 Actions 页面手动运行完整数据校验
- **监控范围跳过导致状态与待核实项丢失**：`--scope local` 过去只保留 local 目标，`--no-browser` 混合产品会直接丢掉 browser 目标；随后队列按当前 targets 重建，CI 目标、健康异常和未核实变更可能被静默清除。现在两个方向的范围跳过、局部重试与 browser 跳过都沿用旧目标状态，只标 `skipped_this_run`
- **定向 `--resolve` 参数解析错误**：文档中的 `--resolve <product_id> [target]` 会把 target 解析成另一个产品 ID，导致整个产品的待核实项和告警被清除。改为显式解析产品与可选目标，并补临时仓库回归测试
- **CI 旧产物 rebase 竞态**：publish 过去先生成、后 rebase，可能把旧真源生成的 bundle/feed/API 叠到新提交上。现在先同步最新 main，再生成与复验；生成后不再 rebase，push 失败即整轮不部署
- **webhook 凭据泄露与过期通知**：请求异常日志可能包含 Telegram bot token，现按 bot token、查询参数和 URL 用户信息脱敏；工作流记录本轮起点，通知脚本只发送本轮写出的状态，避免前置步骤失败时重发旧告警
- **浏览器子资源 SSRF 校验绕过**：Playwright 路由过去对非 IP 主机名跳过 DNS 校验，现对每个请求执行完整公网地址检查；DNS 无法验证时浏览器路由失败关闭，requests 保留原有网络失败路径
- **监控基线覆盖与空白误报**：未 resolve 的 A→B→C 变更现在固定保留首次 `prev.txt`，同日多次变更追加时间后缀；中英文边界或中文之间的空白排版变化只更新基线，不再进入待核实队列（`HASH_SCHEME` 升至 `text-v6`），英文词边界仍参与哈希
- **`--fail-on-error` 被 changed 聚合状态掩盖**：同一产品一个目标 changed、另一个 failed 过去仍退出 0；现在按目标级失败计数返回非零，并在 `meta.failed_targets` 中单独记录
- **本地监控脚本夹带暂存改动**：`local_monitor.sh` 现在只对四个监控产物执行 `git diff --cached` 与路径限定提交，不会把用户预先暂存的其他文件带进监控提交
- **页面告警与信息语义**：详情页新增抓取异常卡片（健康队列缺失时从状态兜底）；首页显示未检查目标数量、近 30 天人工核实覆盖，训练统计明确包含“疑似”；详情页显示版本核实日期，未知训练场景的去标识化不再显示为明确“否”
- **政策数据纠错**：AutoClaw 个人版由“明确不训练”改为未知；GLM 摘要风险与红色字段统一；MiniMax 去标识化明确为“未证明而非否定”；商汤移除引文中的评述；Claude 删除无出处的“5 年留存”并改用本地可核实英文原句
- **可灵 AI 抓取降级修复**：`requests` 只返回导航空壳，改为 `fetch_method=browser` + `.document-view-agreement` 后稳定取得完整正文；与旧有效快照对比仅移除页首导航，条款无变化，已重建基线、清零健康队列并更新核实日期
- **文档与流程图审计漂移**：按当前 `origin/main`（`47c6b60`）统一内部架构图、交互流程图与维护文档口径——CI 为全量回归测试及 README / docs / product / feed / API 五项检查、生成五类产物；监控生成 feed 并可选 webhook；首页与详情页的 pending/health 读取边界、local / partial / `--no-browser` 语义、CI 生成前同步流程均已校正；删除不可达的 `changed + rebaselined` 组合，并明确 browser 仅按目标配置启用、不承诺零漏报
- **`prune_orphan_snapshots` 数据丢失边界**：`load_policy` 读 JSON 失败返回空 dict，prune 此前把"配置里没有活跃目标"的空 dict 产品当成孤儿，把其全部快照目录 `rmtree` 删光，且 monitor.yml 会把删除 commit 进历史——一次数据文件损坏等于永久丢掉该产品的快照 diff 历史。现在读取失败（空 dict / 非 dict）的产品整目录保护，只有配置里明确不再监控的目标才清理；补回归测试
- **监控状态时间戳混用两种时钟**：`check_updates.py` 14 处裸 `datetime.now()` 无时区标记，GitHub runner（UTC）与本地（UTC+8）写入混存，前端展示存在 8 小时歧义。统一改为北京时间（`PROJECT_TZ` + `now_iso()`，与 `validate_data.py` 的 `last_verified` 同口径）
- **`fetch_with_retry` docstring 失实**：注释写"指数退避"，实现是线性（`RETRY_BACKOFF × 尝试序号`）；按实现修正措辞
- **失败原因汇总误判**：此前对整条 message 做裸子串匹配（`"SSLError" in msg`、`"403" in msg`），URL 里恰好含 "403"/"429" 时会把拒绝访问误判成限流。改为按抓取层写入的结构化前缀解析（`检查失败：HTTP <code> 错误 - …` / `检查失败：请求异常 - <异常类名>`），并补充 401/451/重定向超限/响应超限等映射

- **内部流程图与文档描述校正**：`docs/architecture.html` 六处描述与代码不一致——回归测试实际 141 项（原写 121）；顶部“人工核实日期”优先取全部产品 `last_verified` 最大值、缺失才回退 `meta.last_updated`（原写直接取后者）；ci.yml concurrency 为 `cancel-in-progress: false`，同一分支多次推送串行执行、不取消旧运行（原描述“只保留最新一次”与设置矛盾）；监控 banner 实际文案为「检测到 N 个产品政策可能已更新」；OG 卡片由部署工作流现场生成、CI 不再重生成提交（`site/generated/og-card.png` 是历史遗留的入库旧副本）；bundle.json 约 33KB。同步修正 `docs/architecture.md`、`AGENTS.md`、对外文档 `site/docs/data-pipeline.md`（并澄清比对基于归一化文本全等、SHA256 仅作记录）并重生成 HTML；ci.yml 的 concurrency 注释同步改为与设置一致
- **展开详情后表格列宽漂移**：产品行展开的 `colspan` 详情内容参与自动布局，会把「个人版」等列挤走。`#compareTable` 改为 `table-layout: fixed` 并显式分配列宽，窄屏单独分配，展开前后表头零位移
- **CI 时区误判**：`validate_data.py` 与回归测试原用 runner 的 UTC 日期判断 `last_verified` 是否为未来日期，北京时间 00:00–08:00 会把当天数据判错；改为统一按 Asia/Shanghai 计算“今天”
- **表格表头吸附失效**：`.table-wrapper` 的 `overflow-x: auto` 使它成为滚动容器，`thead th { position: sticky }` 在纵向不生效，48 行滚到后面完全看不到列名。桌面改为放开 overflow、表头吸附在 56px 顶栏下方；窄屏改为容器内滚动
- **首页“人工核实”日期过期**：页面一直显示 `meta.last_updated`（2026-08-31），与实际 `last_verified`（2026-10-22）脱节，且 Hero 只显示 `MM-DD` 丢年份。改为数据驱动并显示完整日期
- **小字对比度不足**：`--text-tertiary` 在深色背景上仅 4.14:1，低于 WCAG AA；调至 `#8b8b94`（约 5.9:1），并补对比度回归测试
- **首页主表训练列全部显示"未明确"**：`trainCell()` 读取的是版本对象的 `training_status`，调用处却传了 `toc && toc.used_for_training` 布尔值，导致 48 行两列全部落到 `unknown`。改为传 `toc` / `tob` 对象，并补回归测试
- **监控失败导致 Pages 部署被跳过**：`monitor.yml` 因单个目标超时会失败，而 `deploy.yml` 只认上游成功，线上数据会被冻结一周。部署条件改为：数据校验失败仍不部署，但"政策更新监控"失败时照常部署已提交的结果
- **时间戳标签含 `(UTC)` 时未剥离**：`最后更新时间 (UTC)：2026-10-15` 会泄漏进哈希，日期更新被误报为政策变更；正则现允许标签与冒号之间的时区/地区后缀
- **局部重试虚增健康轮次**：`--products/--only` 未检查的产品现在会标 `skipped_this_run`，`consecutive_runs` 不再因重试其他目标而上涨
- **`min_body_chars: 0` 被忽略**：配置值 0 不再被 `or` 回退成默认 500
- **修复"最后更新时间"标签匹配失败**：`DYNAMIC_TIMESTAMP_RE` 里写成字符组 `最后更新[时间]?`，而 `[时间]` 只匹配一个字符，导致"最后更新时间："（阿里云帮助中心的实际写法）整体匹配失败、时间戳泄漏进哈希；同时补上点号分隔格式（火山方舟协议页文末"最近更新时间：2026.09.18 14:35:02"）
- **正文过短时记录实际页面线索**：新增 `describe_shell()`，把标题与页面首段写进 message，让"正文仅 0 字符"能区分 Cloudflare 挑战页 / 登录墙 / 404 / 纯空壳——这几种处置完全不同，此前 CI 日志里只有一句"正文仅 0 字符"，无法判断
- **`trae` 抓取修复**：配 `targets.main.content_selector: "[class*=content]"`（属性包含选择器，不受构建 hash 影响）+ `wait_for_selector`。修复后正文由"导航+正文"变为纯正文，`TraeCode`/`定价`/`登录` 等导航词消失而"隐私政策"×33、"个人信息"×81 零差异。**但 CI（美国 runner）上仍连不上**——`describe_shell()` 显示"实际拿到：空文档"，即 Chromium 根本没拿到响应 HTML，属连接层失败（Cloudflare 对数据中心 IP）而非渲染问题，本地可正常抓取。这类环境差异无法靠抓取配置消除，只能换源或申请放行；`degraded` 语义保证快照有效、页面继续展示上次正文、恢复可达后自愈
- **`doubao-api` 波动定性并根治**：CI 上曾抓到 2.09 万字符版本，一度无法判定是"更完整"还是"重复渲染"。对照确认是**重复渲染**——关键词计数精确翻倍（`豆包大模型服务协议` ×2→×4、`输出内容` ×9→×18），且 2.09 万 = 1.15 万 + 一份完整 9345 字符协议正文。基线取单份版本，配合 `wait_until_text_stable()` 后连续多轮稳定
- **`zread` 复核**：`/terms`、`/privacy` 仍 404；`/legal/terms` 返回 200 但是 SPA 空壳（110KB HTML，正文仅一句 UI 文案，全文不含协议/条款/隐私字样）。确认无公开政策页，`monitor: false` 维持不变
- **`gemini` 补充大陆可用性说明**：`key_findings` 标明 Google 未在中国大陆境内运营 Gemini，本表记录的是官方条款原文，中国大陆用户无法通过官方渠道使用
- **Gemini 监控 URL 锁定地区与语言**：`policies.google.com/terms` 按访问来源 IP 切换国家版本条款（本地新加坡 / CI 美国），每次换网络环境都报 changed 且 `--resolve` 只能掩盖。`policy_url` 与 `versions.toc.policy_link` 加 `gl=US&hl=zh-CN`（`gl` 覆盖 IP 推断，锁 CI 所在地区以统一本地与 CI 基线；`hl` 影响远大于 `gl`，英文版 56422 字符 vs 中文版 24854 字符）。锁定前实测三地区对比：`main` 的 CN 与 SG 版仅差"国家/地区版本"标签、正文一字不差，`toc` 的 CN 与 SG 版哈希完全相同，核心政策表述（默认 18 个月留存、3/36 个月选项、人工审核、训练新模型）三地区逐条一致——锁任一地区均不改变本表记录。理由与实测数据已写入 `verification_notes`
- **修复 CI 从未真正提交过监控结果**：`ci.yml` 的 publish job 与 `monitor.yml` 都要 `git push` 生成物，但两处 checkout 都写了 `persist-credentials: false`，push 直接失败（`could not read Username for 'https://github.com'`）——仓库历史上没有任何 bot 提交，监控状态与快照每次都跑完就丢。改为这两个 job 保留 checkout 凭据（写权限仍由 `permissions: contents: write` 限定到最小范围），不 push 的 validate/deploy job 仍关凭据。补 `test_push_jobs_keep_checkout_credentials` 锁定
- **修复 bot 提交与人工提交竞争**：监控运行期间若有人 push（本地核实、CI 再生成产物），bot 的 push 会被拒（`fetch first`）而整轮结果丢失。提交前先 `git pull --rebase --autostash origin main`
- **修复 SSRF 防护误杀合法公网 URL**：`safe_fetch_url` 把"DNS 没解析出来/解析超时"和"解析到私有地址"混为一谈，GitHub runner 上偶发慢解析就让合法公网 URL 被记成"仅允许解析到公网地址的 HTTPS URL"，真实故障原因被安全策略掩盖。现在只有**明确解析到私有/保留地址**才拒绝，无法判定时放行让请求自然失败（解析不出来时后续连接同样会失败）；DNS 等待上限 3s → 5s
- **修复 browser 抓取的"提前退出"导致基线不稳定**：曾用"正文超过 8000 字符就提前结束渲染重试"来省时间，但各页面完整正文长度差异极大——实测 `support.google.com` 帮助页同一次抓取出现过 9500 与 56422 字符两种结果，固定阈值会把渲染未完成的中间态写进基线，之后每轮都误报 changed。现固定跑满 3 次渲染并取最长（`pick_longest_render()`），额外成本远小于误报代价
- **正文起始标记只用站点特有格式**：`LEAD_IN_MARKER_RE` 曾加入中文 `生效日期：`，导致腾讯系协议页开头的「文档标题 + 更新日期」被整段切掉（tencent-yuanbao 少 26 字符、ima 少 62、yuanqi 少 28）——这些字段是政策版本标识。现只用 OpenAI/英文站的 `Published:` / `Updated:` + `YYYY年`，并加 `test_lead_in_marker_keeps_chinese_title_and_update_date` 锁定
- **新增两条 UI 去噪规则**：chatgpt/tob 的语言下拉列表展开与否（15147 ↔ 15752 字符）改由头部截断处理；doubao-api 的新手引导浮层（11564 ↔ 11593 字符，差异仅"我知道了 不再提醒"按钮文案）进 `UI_NOISE_PHRASES`
- **`doubao-api` 锁定稳定正文容器**：文档站页面结构波动（有时包 `<main>`、有时不包），`extract_text` 的 root 在"仅正文"与"导航+正文"间跳变。配 `targets.main.content_selector: "#app-content"`（用稳定 id，不用带构建 hash 的 class）后连续多轮稳定
- **修复 13 个 JS 空壳目标的抓取配置**：实测 12 个目标的静态 HTML 只有空壳（`#app`/`#root`/`#__next` 空 div、`BAILOUT_TO_CLIENT_SIDE_RENDERING` 占位），配 browser 后正文从 0 字符恢复到 1.1 万～5.6 万字符。其中 7 个目标此前处于**"假健康"**——旧 baseline 存的是页面标题或导航噪声（如 skyproduction 存的是产品首页标题「天工工作台 - AI视频生成工具」），因此长期显示"内容未变化"；修复后首轮必然报 changed，经 diff 确认为抓取方式变化而非政策变更，已逐条 `--resolve` 承认新基线
- **Gemini 目标改用 browser 后恢复可抓取**：`policies.google.com` 等域名在受限网络下 requests 层连接超时（3 个目标长期 `degraded`），但 Chromium 网络栈可正常访问，health 全部回到 `ok`。因 browser 固定 `locale=zh-CN`，Google 返回中文版而非原先的英文版，构成一次抓取层面的 changed（非政策变更），已 resolve
- `baichuan` 此前疑似登录/验证码墙（静态 HTML 含 `captchaContainer`），实测 browser 渲染后可拿到完整《百川用户协议》（13437 字符），因此保留 browser 监控而非 `monitor: false`——**先试跑拿证据再决定降级方案**
- **不可达域名的重试预算**：连接阶段超时单独收紧到 5s（requests 会按解析出的每个地址依次连接），并为单目标网络重试加 120s 墙钟预算。`policies.google.com` 在受限网络下原本单目标要耗 5 分钟以上、3 个 Gemini 目标足以吃掉一轮监控预算，现在约 105s/目标
- `update_status.json` 的 `meta` 新增 `health_issues` / `health_blocked` / `health_degraded` / `health_no_baseline` / `partial_run`
- 监控工作流超时 30 → 45 分钟，请求间隔 1.5s → 0.5s、单次超时 30s → 20s（全量一轮从超时被杀变成稳定跑完），并提交 `monitor_health.json`
- **监控可靠性修复**：304 仅在本地基线有效时接受；缺基线会强制完整抓取并标记 suspicious，URL 变化进入待核实，队列告警在 resolve 前保持可见
- **数据模型修复**：新增 `training_status` 语义化训练结论和 `sources[]` 补充来源注册表；正文提取支持 PDF、main/article 和动态节点过滤
- **安全边界修复**：监控仅允许公网 HTTPS URL，文档 Markdown 输出清洗原始 HTML，政策链接使用 URL 协议白名单

- **监控/核实流程重构（端到端）**：CI 不再做 AI 分析、不再自动建 Issue。`monitor.yml` 只保留 `check_updates.py` 检测 + 快照入库 + 写 `pending_verification.json` 待核实队列；核实与改数据全部在本地由 `policy-change-verify` skill 完成。移除 `scripts/analyze_changes.py` 与 `OPENAI_API_KEY` 依赖
- **基线方案无关化**：变更检测改以"已入库快照文本"为准（哈希仅作快速路径），哈希方案升级（text-v2→text-v4 等）时不再整库误报/失明；快照 `site/generated/snapshots/` 由 `.gitignore` 忽略改为入库，作为跨环境（CI↔本地）共享的持久历史；日期存档加保留策略（默认 12 份）
- **站点整体迁入 `site/`（方案 D）**：`site/` 即站点根，内含 `index.html`、`detail.html`、`404.html`、`robots.txt`、`sitemap.xml`、`css/`、`js/`、`data/`、`generated/`、`docs/`；仓库根只留文档与工具（21 → 12 项）
- **部署改用 GitHub Actions**：新增 `.github/workflows/deploy.yml`，发布 `site/` 目录；Pages 设置需一次性改为 *Settings → Pages → Source: GitHub Actions*（原因：分支发布只支持 `/(root)` 或 `/docs`，无法指定 `site/`）
- 部署触发用 `workflow_run`（监听「数据校验」「政策更新监控」完成）而非 `push`——bot 用 `GITHUB_TOKEN` 提交的 commit 不会再触发 `push` 事件，否则自动生成的产物发布不出去
- 脚本路径常量全部改为 `site/data` 与 `site/generated`；`start.sh` 改为 `http.server --directory site`；新增 `site/.nojekyll`

- **目录分层**：`site/data/` 只保留人工维护的源数据（`products.json` + `policies/`）；生成物统一放 `site/generated/`——`bundle.json`、`update_status.json`、`pending_verification.json`、`snapshots/`，以及原 `assets/og-card.png`（`assets/` 目录已移除）
- **风险等级校准**：4 处"训练且无退出机制却标黄"改为红（`zai.toc`、`kimi.tob`、`bigmodel.tob`、`glm-coding-plan.toc`），README 汇总表与 OG 图已重新生成（高风险 15 → 17，中风险 24 → 22）
- **方法论口径修订**：红色标准第③条明确为"**训练场景下**未进行去标识化处理"，消除与约 15 个 `deidentified=false` 黄色块的规则冲突
- **文档单源化**：新增 `scripts/gen_docs.py`，`site/docs/*.md` 为唯一源、`*.html` 由脚本渲染，CI 跑 `--check` 并自动提交，彻底消除两份手工副本的漂移
- **首页瘦身**：`bundle.json` 按白名单裁剪（只含表格与展开面板所需字段），202 KB → 30 KB；Google Fonts 改为异步加载（国内访客不再因字体请求阻塞而白屏）；详情行改为展开时才渲染
- `key_clauses` 纪律：非政策原文内容（对比提示、404 核对记录）移入新增的可选字段 `verification_notes`
- 占位条目（政策 URL 只能指向产品首页）新增可选字段 `monitor: false`，监控脚本跳过，避免持续误报
- 补齐 3 个产品"引文出处"的监控目标（`versions.toc.policy_link`，人工确认）：`zcode` → `zcode.z.ai/cn/privacy`；`xunfei-xinghuo` → 《讯飞星火APP用户协议》（`xinghuo.xfyun.cn/policy/`，原 `xfyun.cn/doc/spark/UserAgreement.html` 已 404）；`tencent-yuanbao` → 《腾讯元宝隐私政策》（`privacy.qq.com/document/preview/eb9be565...`）

### Removed

- **剔除 `zread` 占位条目**：Zread.ai（智谱 GitHub 项目解读工具）经三轮人工核实（2026-08-30 / 09-19 / 09-27）确认无独立公开政策页（/privacy、/terms 404，/legal/terms 为 110KB SPA 空壳），占位条目只产生横幅常驻"1 个产品未监控"与一行未评定数据、零政策内容。`monitor: false` 机制保留供未来同类场景使用；若智谱日后发布 zread 条款，可按 `add:` 流程重新收录（三轮核实记录在 git 历史与内部文档中）。产品数 48 → 47，`index.html` 硬编码计数同步更新，bundle/详情页/sitemap/README 表/OG 卡片已重新生成

### Added

- `tests/test_scripts.py` 新增 `test_site_dir_is_the_publish_root`：断言站点根文件齐备，防止漏文件导致线上 404
- `tests/test_scripts.py` 新增 `TestLayout`：断言源数据目录不含生成物、前端只从 `generated/` 读取
- `tests/test_scripts.py` 新增 `TestResponseDecoding`（4 项）：防止响应解码回退到 latin-1 再次产生乱码快照
- `tests/test_scripts.py` 新增 `TestSiteConsistency`（6 项）：页面内相对链接可达性、资源版本号一致、sitemap 与产品索引一致、`deploy.yml` 的 `workflow_run` 名字匹配、bundle 瘦身且完整、文档页无"未来功能"等过时表述
- `scripts/gen_docs.py`：把 `site/docs/*.md` 渲染为发布用 `.html`（依赖 `markdown`，已加入 requirements.txt）

### Fixed

- **修复政策正文快照乱码**：`requests` 对未声明 charset 的 `text/html` 会按 RFC 2616 回退到 ISO-8859-1，中文被解成拉丁字符后再以 UTF-8 存盘，形成双重编码（mojibake），快照无法阅读、AI 变更分析也拿不到有效文本。新增 `response_text()`：未声明 charset 时用探测编码（兜底 utf-8），声明为 ISO-8859-1 的尝试反向还原
- `HASH_SCHEME` 升至 `text-v2`：解码变化会让所有哈希改变，升版后脚本重建基线，避免误报"全部产品政策已变更"
- 修正 `docs/update-monitoring` 中「`update_status.json` 已加入 .gitignore」的过时描述（该文件现已入库，由监控流程提交）
- **文档页 CSS 死链**：`site/docs/*.html` 引用 `../site/css/style.css`（迁移 `site/` 后的遗留路径），部署后 404 导致两个已收录页面完全没有样式
- **8 个纯 ToB 产品详情页首屏空白**：`syncTabs` 只隐藏了标签按钮，没把 `active` 从 `contentToc` 移到 `contentTob`
- **资源版本号分裂**：`index.html` 用 `20260916-1`、`detail.html`/`404.html` 用 `20260909-1`、docs 页无版本号，现统一为单一版本（测试已锁死）
- **监控空转**：12 个产品的正文快照只有 19–93 字节（SPA/反爬只返回标题骨架），却仍记为 `ok` 并建基线；现对低于 `MIN_BODY_CHARS` 的正文标记 `suspicious`，不建基线、不报变更
- **AI 变更告警在最后一公里丢失**：无旧快照的报告缺少 `has_substantive_change`，被摘要的 True/False 两分过滤同时漏掉；现补为 `True`，且 Issue 正文始终逐条列出变更产品
- **状态与队列一致性**：监控会拒绝没有本地基线的 304，未解决的 changed 告警不会被后续 304 清除；队列解析失败时停止写入而不是覆盖历史
- **git 历史回退是死代码**：把绝对路径当作 git pathspec 传给 `git log/show`，永远不会命中，改为 `os.path.relpath`
- **哈希方案覆盖提取器变体**：bs4 与正则回退剥离的标签不同，`HASH_SCHEME` 现形如 `text-v4-bs4` / `text-v4-regex`，避免依赖缺失时全库哈希漂移造成批量误报
- **数据文案与字段矛盾**：`zhipu-qingyan`（摘要说"退出需发邮件"、字段是设置开关）、`ima`（摘要说"评为低风险"、字段是 yellow）
- **脚本健壮性**：`update_status.json` 改为原子写（tmp + `os.replace`）；单个数据文件损坏不再中断整轮监控；全部产品失败时显式告警；`validate_data.py` 补齐漏检（`null` 值、非 dict `versions`、版本块非对象、`policy_link` 非 URL、`region` 枚举、未来日期、`timeline` 日期格式）
- **文档数字口径**：README、首页和方法论统一为 48 款产品、63 个版本块，并同步更新 ToC/ToB 展示说明；`SECURITY.md` 支持版本补 1.3.x，并移除已不可用的"GitHub 站内私信"联系方式

## [1.3.0] - 2026-09-18

### Fixed

- **修复线上死链**：`docs/` 曾被 `.gitignore` 整体忽略，导致首页"方法论"链接与 `sitemap.xml` 中的 `docs/*.html` 在线上 404。现拆分为：`docs/`（对外发布页面，入库）+ `docs/internal/`（内部工作底稿，忽略）
- `data/update_status.json` 与 `data/bundle.json` 不再被忽略（首页依赖其展示监控状态与加速加载），工作流不再需要 `git add -f` 强推

### Added

- `CODE_OF_CONDUCT.md`（行为准则）、`SECURITY.md`（安全政策）
- `CHANGELOG.md`（本文件，原更新日志从 README 迁出）
- `tests/test_scripts.py`：数据与脚本的基础回归测试（unittest，无第三方依赖）
- `.github/dependabot.yml`：曾配置 GitHub Actions 与 pip 依赖自动更新检查，后续按维护策略移除，升级依赖需人工审阅
- `CONTRIBUTING.md` 增加 English quick start 段落

### Changed

- `ci.yml` 拆分为 `validate`（`contents: read`）与 `publish`（仅 main 推送、`contents: write`）两个 job，遵循最小权限原则
- `ci.yml` / `monitor.yml` 增加 `concurrency` 分组，避免并发运行互相覆盖提交
- README 顶部增加 CI / 许可证 / 数据量徽章

## [1.2.0] - 2026-09-12

### Added

- **第二层 AI 辅助变更分析**：新增 `scripts/analyze_changes.py`，监控检测到政策页面变化后自动对比新旧快照，调用 LLM 提取训练政策/退出机制/留存期限等维度变化，生成结构化报告嵌入 Issue
- 支持任何 OpenAI 兼容 API（OpenAI / DeepSeek / 智谱 / Moonshot 等），未配置 API key 时降级为纯文本 diff
- **SEO 与站点**：新增 `404.html`、`robots.txt`、`sitemap.xml`（53 个 URL）、canonical 链接、`<noscript>` 降级提示

### Changed

- `check_updates.py` 变更时自动备份旧快照到 `prev.txt`；429 限流处理（Retry-After）
- `monitor.yml` 新增"AI 辅助变更分析"步骤；pip 缓存；`timeout-minutes: 30`
- **前端优化**：搜索防抖（200ms）、分组折叠状态保持、OG 标签动态更新、风险图例加方法论链接
- **代码质量**：CSS/JS 版本号统一、`.editorconfig` 代码风格配置、`gen_og_image.py` 跨平台字体回退、CI 自动生成 OG 图片
- **文档**：README 目录结构补全、methodology 数据源表更新为 50 款产品、CONTRIBUTING 脚本说明补全、update-monitoring 第二层分析文档

### Fixed

- 数据修正：`VENDOR_SORT` 补字节跳动（app.js + gen_readme_table.py）

## [1.1.0] - 2026-08-29

### Added

- 新增 `scripts/validate_data.py` 数据校验脚本（schema、ID 一致性、占位文字检测）
- README 汇总表改为从数据自动生成（`scripts/gen_readme_table.py`）
- 首页展示监控状态：检测到政策变更时显示告警横幅并在产品名旁标注 ⚠️
- 新增 `start.sh` 一键启动；全部 Python 脚本统一走 `.venv` 虚拟环境
- 新增 favicon、页面 meta 描述

### Changed

- 数据单源化：产品详情数据只保留在 `data/policies/{id}.json`，`products.json` 改为 ID 索引
- 监控脚本改为正文文本归一化哈希 + ETag/If-Modified-Since 条件请求，大幅减少动态页面误报
- 监控脚本支持请求间隔（`--delay`）、失败重试、哈希算法版本化（升级时自动重建基线）
- 前端重构：抽取 `js/common.js` 共享工具；ToC/ToB 与筛选状态写入 URL 可分享；表格行支持键盘导航
- 徽章类名语义化（`badge-good`/`badge-bad`）；筛选按钮改用"低/中/高风险"文案

### Fixed

- 修复 README 汇总表与数据的多处不一致
- 全量数据核实（AI 辅助 + 人工确认）：8 个产品的留存期限/条款摘录按官方政策原文更新，修复 8 条失效政策链接，修正 4 个企业版风险等级

## [1.0.0] - 2025-01-15

### Added

- 初始版本发布：12 款主流 AI 产品的政策对比数据（后扩展至 50 款）
- 支持个人版 (ToC) 和企业版 (ToB) 切换
- 支持风险等级筛选和产品搜索
- 产品详情页包含时间线、关键条款摘录、分析摘要
- 政策更新监控脚本 `check_updates.py`
- 方法论和监控说明文档
