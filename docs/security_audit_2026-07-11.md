# EvoExternMath-S1++ 安全加固收口报告（2026-07-11）

## 结论

在本轮代码、测试、提交导出、dry-run、trace/provenance、模型调用、工具执行与敏感信息扫描范围内，未发现仍可复现的 P0/P1。最终综合门禁与 mock 预提交门禁均通过；本轮未调用真实 API，也未修改或伪造官方结果、trace 或评测记录。

“未发现”仅针对当前代码树和已执行的对抗用例，不等于对未来依赖版本、运行主机或外部模型语义正确性的绝对保证。剩余低风险见下文。

## 修改前备份

- 原始项目快照：`C:\Users\y\OneDrive\Desktop\挑战杯\主代码仓\miniature-parakeet-挑战杯-20260709-完整备份-20260710-213505.zip`
  - SHA-256：`6795DC8AC08D0FD922FDF531E62B7E141AC219E81D37923B20481C169063E03B`
- 当前工作仓修改前快照：`C:\Users\y\OneDrive\Desktop\挑战杯\主代码仓\miniature-parakeet-git-修改前完整备份-20260710-213549.zip`
  - SHA-256：`5C5A7B7BAECD413A31A4E104F68968A76CAB27319DEB65F7FA63C2E2B392542E`

## 已关闭的主要风险

1. **结果与成功契约**：`success` 必须同时具备非空最终值、通过的验证和空错误；proof 不再自动放行。
2. **执行与提示词 provenance**：结果绑定输入、执行配置、提示词原始字节摘要、mock/real、模型、端点摘要、trace 策略和运行模式；resume、metrics、export 共用验证逻辑。
3. **trace 完整性**：绑定完整结果、路由、最终 verifier、模型/工具调用、时间、有限非负延迟、提示词版本和互斥 mock/real 标记。模型调用只在真实 `client.chat` 边界计数；真实成功必须以独立 verifier 调用结束。
4. **严格 JSON**：批处理、模型输出、HTTP/worker、MemoryHub、debugger、shadow eval、demo evidence、工具子进程等不可信入口拒绝重复键、`NaN`、`Infinity` 和非有限数。
5. **API 隔离**：仅接受 HTTP 200，禁止重定向，限制请求/响应/重试/总时限；子进程具备硬截止和资源限制；`requests.Session(trust_env=False)` 禁止 netrc 和环境代理覆盖显式 Bearer。
6. **工具执行**：Python 工具限定为有界算术 AST；SymPy 走独立、allowlist、限时限内存 worker，失败关闭。
7. **dry-run**：仅接受完整、strict、canonical 的 `SolveResult`；输入 manifest 在结束前复核；ID 规范化后去重；trace 使用独占 `<base>/<run_id>`；直接构造配置也会再次校验。
8. **提交导出**：结果/trace/profile 严格绑定；路径按跨平台规则校验；目录与 ZIP 使用原子事务和身份复核。ZIP 拒绝注释、SFX 前缀、成员间隙、额外字段、尾随字节、ZIP64/多磁盘和未清单元数据。
9. **敏感信息扫描**：覆盖常见源码/配置/日志及未知 UTF-8 文本；强凭据字段的短值、纯字母值、特殊字符值均失败关闭；测试夹具仅允许精确、结构化样例，不能用 `TEST/MOCK/EXAMPLE/REALVALUE` 等子串绕过。
10. **路径与写入**：关键 JSON/JSONL/report/trace 使用有界读取、物理路径/链接检查、文件身份复核和原子写入；生成产物在安全扫描前清理。
11. **Preview 隔离**：Voting 保持默认关闭；Proof Guardian 仅作风险/人工复核依据；MemoryHub 默认不写入；未加入产品级 MultiAgent。
12. **源码来源**：CLI、脚本和 `user_agent.py` 强制优先加载当前 checkout 的 `src`，门禁验证模块来源，避免旧 editable install 混入。

## 二次复核关闭项（公开 Demo 与供应链）

1. **Streamlit 写入边界**：Demo 固定为 `mock=True`，不再接收 `trace_dir`、`question_id` 或 real 模式输入；服务端使用固定根目录、随机 session 子目录及不可复用 trace ID，消除了页面参数驱动的现有 JSON 覆盖路径。
2. **Streamlit 回放边界**：页面不再接收文件路径；只枚举当前 session 内符合命名规则且非链接的 trace ID，并在读取前再次验证成员与根目录。
3. **真实 API 主机策略**：real 模式新增必填 `INTERNS1_ALLOWED_HOSTS` 精确主机白名单；拒绝 IP 字面量、localhost、单标签名、私有风格后缀及不在白名单内的主机，且 preflight 在发送授权信息前执行相同校验。
4. **安全扫描器盲区**：`outputs/.gitkeep` 与 `outputs/traces/.gitkeep` 必须是普通零字节文件；非空、非 UTF-8、目录替代及秘密样例均失败关闭。`.gitignore` 同步覆盖 `.env.*`、私钥/证书/密钥库和根 trace 产物，同时保留 `.env.example` 与两个占位文件。
5. **trace 脱敏**：除已知令牌格式外，新增长度、字符类别和熵联合判定的未知裸令牌兜底；保留 SHA-256 指纹、低熵标识符及 Python 类路径，避免破坏 trace provenance。
6. **SymPy 与进程预算**：复数数值指数按复数模长执行绝对上限；Python、SymPy、HTTP 三类隔离 worker 共用进程内 4 槽预算，容量耗尽时失败关闭而不继续创建子进程。
7. **batch trace 失败路径**：缺失 trace 的预算结构补齐 `file_bytes=0`，避免 trace 写入失败后聚合阶段出现 `KeyError`。
8. **依赖与 CI**：新增 runtime/dev 全量精确版本及 SHA-256 锁文件；CI 以 `--require-hashes` 安装，设置 `permissions: contents: read`、`persist-credentials: false`，并将 checkout/setup-python 固定到官方发布提交。

## 复检后补充关闭项

1. **Demo 留存与请求预算**：每 session 最多 50 条 trace、8 MiB，总服务最多 64 个 session、512 条 trace、64 MiB；单 trace 512 KiB、TTL 1 小时、同 session 求解最短间隔 2 秒。session/root 枚举分别设置硬 entry cap，先有界清理过期内容，仍超限则拒绝新写入，不跟随目录链接。
2. **Demo 匿名入口预算**：题目在任何限流状态、trace 分配和 pipeline 执行前强制限制为 8,192 字符及 32 KiB UTF-8；在 session 间共享 30 次求解/分钟、新 session 16 个/小时、活跃 session 32 个的单进程硬上限，状态具备 TTL 和固定容量，轮换 session ID 不再绕过总入口预算。
3. **DNS 与 origin**：隔离 HTTP worker 对 allowlist 域名只解析一次；所有结果必须是公网单播地址，拒绝环回、私网、link-local、IPv6 ULA、保留/混合地址。验证结果在该 worker 内固定供本次 HTTPS 连接使用，同时保留原 hostname 的 TLS SNI、证书和 Host 语义，阻断二次解析变化。real Bearer 路径仅授权 HTTPS 443，非预期同主机端口在 client preflight 与 worker 两层拒绝。
4. **未知 token 与 provenance 信任**：裸 64 位十六进制、全小写、全大写及 base52 高熵长串现在会脱敏；通用 dict/text/JSON 不再因字段名看似 `sha256` 而放行。只有显式的程序自有 trace/dry-run 写入与读取入口，才在精确结构路径保留合法小写 SHA-256；普通 replay 始终使用不可信脱敏路径。
5. **二进制与 Git 历史**：扫描器明确拒绝 `.jks`、`.keystore`、`.ppk`、`.pkcs12`、`.p12`、`.pfx`；对其他二进制执行有字节上限的高置信凭据扫描。Git 扫描覆盖可达 commit/tag message、普通 patch、真实二进制和被 attributes 标为 binary 的 blob，三条流共享 commit/字节/时间上限；测试值仅在当前文件含显式 sentinel 且值精确匹配合成夹具时 scrub，发现后只报告风险类型和 `[git-history]`，不回显内容。
6. **交付追踪**：关键新增 runtime、worker、锁文件及安全回归测试必须存在于 Git 索引；`tests/test_ci_supply_chain.py` 对清单执行 `git ls-files --error-unmatch`。最终交付同时纳入全部已验证 tracked 修改，避免只提交新增文件或只提交已修改文件中的任一半。

## 第四轮复检修复

1. **Windows Git 可执行文件与工作目录**：安全扫描器不再以裸 `git` 启动子进程，也不使用可能隐式搜索当前目录的裸 `shutil.which("git")`。扫描器显式枚举 `PATH` 目录，只向 `shutil.which` 提交绝对 candidate；解析真实物理路径后拒绝 cwd、仓库根及其内部路径，并有界缓存验证成功的仓外绝对 Git 路径。所有 `subprocess.run`/`Popen` 的 `argv[0]` 均使用该绝对路径，环境设置 `NoDefaultCurrentDirectoryInExePath=1`，子进程 `cwd` 固定为已验证的 `git_executable.parent`；待扫描仓库仍仅通过 `git -C <root>` 指定。这样同时关闭了仓库内伪造 `git.exe` 的搜索劫持，以及继承不可信仓库 cwd 所带来的 Windows DLL/辅助文件搜索风险。若没有可信 Git，则历史扫描失败关闭。
2. **trace 内部元数据与展示路径分离**：`read_trace` 在文件描述符身份、大小和读取后状态均通过验证后，独立返回由实际 payload 长度得到的可信 `file_bytes`；对外 `path` 仍只保留脱敏展示值。`read_trace_dir` 与 CLI 的 batch/resume 预算直接消费该可信字节数或程序自有的可信 trace 读取结果，不再对 `[redacted-path]` 等展示标签执行 `lstat`。包含 64 位 hash/token 的 trace 文件名因此既不会泄露，也不会破坏第二次 batch/resume。
3. **SymPy 有界嵌套指数规范化**：每个 `Pow` 的指数先检查所有数值子节点，再在独立操作预算和节点上限内递归重建允许的 `Add`、`Mul`、`Pow` 与白名单函数节点，规范化后再次检查数值子节点；不调用通用 `simplify`。因此 `2**(1001+x-x)` 等符号消项绕过会在进入昂贵求值前失败关闭，复杂或异常规范化同样受 worker 限时、内存和全局进程预算约束。

本轮先在带完整 Git 索引、且工作目录包含高熵随机片段的完整副本中执行验证：`python -m pytest -q` 为 **919 passed，3 skipped**，用于确认随机路径、hash trace 文件名及第二次 batch/resume 回归。随后在源工作仓完成最终门禁：

- `python scripts/run_regression_gate.py`：**PASS，919 passed，3 skipped**；静态检查、`compileall`、CLI mock smoke 与项目安全扫描均通过。
- `python scripts/run_pre_submit_gate.py --dry-run-limit 3`：**PASS，919 passed，3 skipped**；3 题结构化 mock dry-run、安全扫描与产物清理均通过。

上述验证未调用真实 API。

当前残余边界：可信 Git 仍建立在宿主 `PATH` 中仓库外、权限受控的安装目录之上；若宿主 PATH 本身包含攻击者可写的仓外目录，必须由主机权限和部署基线处理。trace 的 `file_bytes` 证明本次受控读取的大小与身份，不能阻止另一有写权限进程在读取返回后再次改写文件；正式冻结仍应保持工作目录单写者。SymPy 的有界规范化和隔离 worker 是资源安全边界，不是对任意符号表达式复杂度或数学语义的形式化证明。

## 最终验证

| 命令 | 结果 |
|---|---|
| `python scripts/run_regression_gate.py` | PASS；919 passed，3 skipped；source provenance、Ruff、Black、isort、mypy、pyright、compileall、CLI mock smoke、清理、安全扫描全部通过 |
| `python scripts/run_pre_submit_gate.py --dry-run-limit 3` | PASS；919 passed，3 skipped；官方样式 3 题结构化 mock dry-run、清理、安全扫描全部通过 |
| `python -m mypy src --show-error-codes` | PASS；69 个源码文件无问题 |
| `python -m pyright --pythonpath C:\Python314\python.exe` | PASS；0 errors / 0 warnings |
| `python -m pytest -q tests/test_project_safety.py` | PASS；75 passed |
| `python -m pytest -q tests/test_export_submission.py tests/test_run_modes.py tests/test_schema.py tests/test_protocol_schemas.py` | PASS；100 passed，1 skipped |
| `pip-audit -r requirements.lock --disable-pip` | PASS；runtime 锁定依赖未发现当前已知漏洞 |
| `pip-audit -r requirements-dev.lock --disable-pip` | PASS；dev 锁定依赖未发现当前已知漏洞 |

预提交门禁默认验证 mock 结构与安全，不把 mock 无法确定求解的题伪报为成功。仅对已知可由确定性 mock 求解的数据集使用 `--require-mock-success`。

## 修改文件清单（按职责分组）

- 核心协议与流程：`src/math_agent/{cli,pipeline,prompting,schemas,logging_utils,io_utils,security,process_isolation}.py`
- Agent/client：`src/math_agent/agents/{planner,refiner,router,solver,verifier}.py`、`src/math_agent/clients/{interns1_client,http_worker}.py`
- 工具：`src/math_agent/tools/{answer_normalizer,python_sandbox,sympy_tools,safe_sympy,sympy_worker}.py`
- 提交与 trace：`src/math_agent/submission/{dry_run,io,report}.py`、`src/math_agent/harness/{memory,trace_reader,weighted_voting}.py`
- 评估/验证/debugger/evidence：`src/math_agent/evaluation/*.py`、`src/math_agent/verification/*.py`、`src/math_agent/debugger/*.py`、`src/math_agent/evidence/demo_pack.py`、`src/math_agent/harness/demo_adapter.py`
- 入口与环境：`math_agent/__init__.py`、`scripts/_repo_bootstrap.py`、`user_agent.py`、`demo/streamlit_app.py`、`pyproject.toml`
- 供应链：`.github/workflows/ci.yml`、`requirements.txt`、`requirements.lock`、`requirements-dev.lock`、`tests/test_ci_supply_chain.py`
- 门禁/导出/报告脚本：`scripts/*.py` 中本轮 git 状态标记为修改的脚本，重点为 `check_project_safety.py`、`export_submission.py`、`run_regression_gate.py`、`run_pre_submit_gate.py`、`run_official_dry_run.py`、`run_real_api_sample_gate.py` 和 `clean_transient_artifacts.py`
- 文档：`README.md`、`docs/{baseline_freeze,full_system_audit,official_dry_run,security_audit_2026-07-11}.md`
- 回归测试：本轮 git 状态标记为修改/新增的 `tests/test_*.py` 及 `tests/conftest.py`，覆盖上述每个边界。

修改前已存在的用户工作（包括 Router/Pipeline 相关改动及未跟踪提交材料）被保留；未执行 reset、checkout 或覆盖式回滚。

## 剩余低风险与人工边界

- **本地并发/TOCTOU（P2）**：同一主机上拥有写权限的并发进程理论上仍可在读取返回后立即改写文件。关键导出会在 staging/发布前再次校验身份、内容和 manifest；正式冻结时应保证工作目录单写者。
- **非外部签名（P2）**：SHA-256 provenance 证明内部一致性，不等价于第三方签名或可信时间戳。需要强对抗审计时，应在隔离主机上为最终包增加外部签名。
- **证明题语义（人工）**：Proof Guardian 不是形式化证明器；证明题必须进入人工语义复核，不能自动宣称正确。
- **未来依赖情报（持续项）**：锁文件只证明 2026-07-11 查询时未命中当前已知漏洞，不能覆盖未来披露。依赖升级必须重新生成哈希锁并重跑 runtime/dev 审计。
- **敏感形态的协议值（P2）**：为保持答题协议，最终答案本身不会被任意替换；日志/trace 会脱敏，输出目录禁止提交，正式导出再次扫描。
- **公开托管边界（人工）**：Streamlit 现在是 mock-only 本地预览，已具备输入、session/全服务留存、全局求解和新/活跃 session 的单进程硬上限，但不提供产品级身份认证；进程重启会清空限流状态，多 worker 也不会共享额度。若未来改为公网多租户服务，仍应增加反向代理鉴权、来源/IP 配额和分布式限流；不得直接重新开放 real 选择器或路径输入。
- **Git 对象边界（P2）**：扫描覆盖当前工作树和有界可达 refs 历史，不把已不可达、仅残留在对象库/reflog 的 dangling object 当作可交付内容。需要分发包含 `.git` 的取证镜像时，应另行执行对象库级秘密扫描或重新克隆干净仓库。

## 回退方式

1. 首选恢复“当前工作仓修改前快照”，其 SHA-256 如上。
2. 若需恢复最初交付基线，使用“原始项目快照”。
3. 本轮未创建提交；也可按本报告的职责分组逐组反向应用工作树 diff。回退后必须重新运行 `python scripts/run_regression_gate.py`。
