# bugfixer — Coding Agent Harness 设计文档

> 由 Superpowers `brainstorming` 技能协作生成。日期：2026-08-14。

## 1. 问题陈述

### 要解决什么问题

Python 项目中，开发者遇到测试失败时，需要手动定位、修改、验证，过程重复且耗时。现有 AI 编码工具多为配置型（在现成 agent 框架之上做配置），缺乏可验证的工程化机制（治理、反馈闭环）。

本项目交付一个**自己编码实现的 coding agent harness 内核**（非配置型），聚焦"自动修 Python bug"专项任务。主循环、治理、反馈均为确定性代码，可用 mock LLM 跑确定性单元测试验证。

### 目标用户

- **Python 开发者**：有失败测试想快速修复，希望 AI 自主定位、修改、验证
- **AI4SE 课程学习者**：研究 harness 内核机制，理解"编码了机制"与"只写了提示词"的区别

### 为什么值得做

- 交付一个**自己编码实现的 harness 内核**（非配置型），主循环/治理/反馈均为确定性代码，可用 mock LLM 单测验证
- 治理维度深入实现：路径白名单 + HITL 状态机 + 命令黑名单，防止修 bug 时误改文件/执行危险命令
- 反馈闭环：pytest 输出解析器 + 细粒度失败分类 + 多轮自我修正
- 核心价值：移除真实 LLM 后，harness 的工具分发、治理拦截、反馈回灌、记忆读写、停机判断仍能用确定性单测验证——这是区分"编码了机制"与"只写了提示词"的硬标准

## 2. 用户故事

遵循 INVEST 原则。

### US1 - 启动修 bug 任务

作为 Python 开发者，我想在 Web UI 输入失败测试节点（如 `tests/test_foo.py::test_bar`）、bug 描述、选择允许修改的文件/目录，点击启动，以便 harness 自主修复。

- *独立*：不依赖其他故事
- *可测*：UI 有启动表单，harness 收到任务配置

### US2 - 自主定位与修复

作为开发者，我想 harness 自主读取测试失败信息、定位代码、修改文件、跑测试验证，多轮迭代直到测试通过，以便我无需手动调试。

- *可测*：mock LLM 返回预设动作，断言主循环执行了 读→改→跑测试 序列

### US3 - 范围围栏拦截

作为开发者，我想 harness 拦截任何白名单外的文件写操作，要求人工确认，以便 LLM 不会误改无关文件。

- *可测*：构造白名单外的写动作，断言被拦截，无需 LLM

### US4 - HITL 确认

作为开发者，我想在 Web UI 看到 diff 预览和命令，点击批准/拒绝，以便我控制每个危险动作。

- *可测*：mock LLM 产生写动作，断言 WebSocket 推送了确认请求，模拟批准后动作执行

### US5 - 失败反馈与自我修正

作为开发者，我想 harness 解析 pytest 输出、分类失败类型（AssertionError/ImportError 等）、回灌给 LLM，以便 LLM 基于结构化反馈修正。

- *可测*：传入 pytest 输出样本，断言解析器提取正确字段和分类

### US6 - 停机与报告

作为开发者，我想 harness 在测试通过/无进展/超时时停机，Web UI 展示结果和动作历史，以便我了解修复过程。

- *可测*：mock 连续相同修改，断言无进展停机触发

### US7 - 凭据安全录入

作为开发者，我想首次运行时引导录入 OpenAI key（隐藏输入），存入系统钥匙串，查看时不回显明文，以便 key 不泄露。

- *可测*：mock keyring，断言存储/读取/清除流程

## 3. 功能规约

### 模块 1：LLM 抽象层（`llm/`）

- **输入**：消息列表 `[{role, content}]` + 系统提示 + 工具描述
- **行为**：调用供应商 API，返回结构化响应
- **输出**：`LLMResponse(content: str, raw: dict)`
- **边界条件**：API 超时/限流 → 重试 3 次（指数退避）后抛 `LLMError`；空响应 → 抛 `LLMError`
- **错误处理**：重试耗尽抛 `LLMError`，由主循环决定是否停机
- **Mock 实现**：`MockLLMClient` 接受预设响应队列，按顺序返回，用于确定性单测

### 模块 2：决策解析器（`core/decision.py`）

- **输入**：LLM 返回的 `content` 字符串
- **行为**：解析 JSON，提取 `thought`/`action`/`action_input`
- **输出**：`Decision(thought: str, action: str, action_input: dict)`
- **边界条件**：JSON 解析失败 → 返回 `DecisionError`，回灌错误让 LLM 重试；未知 action → `DecisionError`
- **错误处理**：解析失败不直接停机，而是将错误信息加入上下文让 LLM 修正；连续 3 次解析失败触发停机

### 模块 3：工具分发器与工具（`tools/`）

**6 个工具**：

| 工具 | 输入 | 输出 |
|------|------|------|
| `read_file(path)` | 文件路径 | 文件内容 |
| `write_file(path, content)` | 路径+内容 | 写入结果 |
| `list_dir(path)` | 目录路径 | 目录列表 |
| `grep(pattern, path)` | 正则+路径 | 匹配行列表 |
| `exec_cmd(command)` | shell 命令 | stdout/stderr/exit_code |
| `run_test(test_node)` | pytest 节点 | pytest 输出 + exit_code |

- **分发器**：根据 `action` 名查表分发，未注册 action → `ToolError`
- **边界条件**：文件不存在 → `ToolError`；命令超时（30s）→ `ToolError`

### 模块 4：治理护栏（`guardrails/`）—— **深入维度**

#### 4.1 路径白名单

- **输入**：`Action` 对象（含 path/command）
- **行为**：对 `write_file` 工具，校验目标路径是否在白名单内；路径规范化为绝对路径（`Path.resolve()`），符号链接解析后校验
- **输出**：`GuardrailResult(allowed: bool, reason: str, requires_hitl: bool)`
- **边界条件**：白名单外 → `allowed=False, requires_hitl=True`，触发 HITL；白名单内 → `allowed=True, requires_hitl=True`（写操作默认需 HITL，可配置自动批准）

#### 4.2 命令黑名单

- **输入**：`exec_cmd` 的 command 字符串
- **行为**：正则匹配危险模式（`rm -rf`, `DROP TABLE`, `git push --force`, `sudo`, `chmod 777`, `curl|wget` 管道执行等）
- **输出**：`GuardrailResult`
- **边界条件**：匹配到危险模式 → `allowed=False, requires_hitl=True`，触发 HITL；未匹配 → `allowed=True, requires_hitl=True`（`exec_cmd` 默认需 HITL，因为 shell 命令是否写文件无法可靠检测，如 `echo > file` 重定向）
- **说明**：`read_file`/`list_dir`/`grep`/`run_test` 为只读操作，`requires_hitl=False`，自动批准

#### 4.3 HITL 状态机

- **状态**：`PENDING`（等待确认）→ `APPROVED`/`REJECTED`（不可逆）
- **输入**：需确认的 `Action`
- **行为**：推送确认请求到 Web UI（WebSocket），阻塞等待用户响应
- **输出**：用户决策 `APPROVED`/`REJECTED`
- **边界条件**：超时（5 分钟）→ 默认 `REJECTED`；用户拒绝 → 动作不执行，回灌"用户拒绝了此动作"；WebSocket 断开 → 默认 `REJECTED`

### 模块 5：反馈校验器（`feedback/`）

- **输入**：pytest 的 stdout + exit_code
- **行为**：解析输出，提取失败测试名、错误类型、错误位置（文件:行号）、错误消息
- **输出**：`TestResult(passed: bool, failures: list[Failure])`，`Failure(test_name, error_type, file, line, message)`
- **失败分类**：`AssertionError`/`ImportError`/`AttributeError`/`TypeError`/`SyntaxError`/`Timeout`/`Other`
- **边界条件**：pytest 输出格式异常 → 返回 `TestResult(passed=False, failures=[Failure(error_type="ParseError")])`
- **错误处理**：解析失败不崩，返回带 `ParseError` 的结果让 LLM 知道

### 模块 6：停机控制器（`core/stop.py`）

- **输入**：当前轮次、测试结果、动作历史
- **行为**：检查三个条件
  - 测试全绿 → `StopReason.SUCCESS`
  - 连续 3 轮修改相同文件相同行 或 相同错误类型 → `StopReason.NO_PROGRESS`
  - 达到最大轮数（默认 10）→ `StopReason.MAX_ITERATIONS`
- **输出**：`StopDecision(should_stop: bool, reason: str)`
- **边界条件**：无

### 模块 7：记忆（`memory/`）

- **输入**：会话 ID、动作记录
- **行为**：追加到 JSON 文件 `~/.bugfixer/sessions/<id>.json`
- **输出**：加载时返回完整会话历史
- **边界条件**：文件损坏 → 返回空历史 + 警告日志

### 模块 8：配置（`config/`）

- **输入**：YAML 文件路径（默认 `~/.bugfixer/config.yaml`）+ CLI 参数
- **行为**：加载 YAML，CLI 参数覆盖
- **输出**：`Config(allow_paths, model, max_iterations, command_blacklist, ...)`
- **边界条件**：文件不存在 → 创建默认配置；解析失败 → 抛 `ConfigError`

### 模块 9：Web 服务（`web/`）

- **输入**：HTTP/WebSocket 请求
- **行为**：
  - `POST /api/tasks` → 创建修 bug 任务，启动 AgentLoop
  - `WS /ws` → 推送动作/状态/diff，接收 HITL 确认
  - `GET /api/sessions` → 会话历史
  - `GET /api/sessions/{id}` → 单个会话详情
- **输出**：JSON 响应 / WebSocket 消息
- **边界条件**：WebSocket 断开 → HITL 默认 REJECTED

### 模块 10：CLI（`cli/`）

- **输入**：命令行参数
- **行为**：
  - `bugfixer` → 启动 Web 服务并打开浏览器
  - `bugfixer key set` → 隐藏输入录入 key
  - `bugfixer key status` → 查看 key 状态（不回显明文）
  - `bugfixer key clear` → 清除 key
- **输出**：启动服务 / 凭据操作结果
- **边界条件**：端口占用 → 自动递增端口

## 4. 非功能性需求

### 性能

- 单次 LLM 调用超时 60s，重试 3 次（指数退避）
- 工具执行超时 30s（`exec_cmd`/`run_test`）
- WebSocket 消息推送延迟 < 1s（本地）
- 10 轮迭代总时长主要受 LLM 响应速度影响，harness 自身开销可忽略

### 安全（凭据威胁模型与对策）

| 威胁 | 攻击面 | 对策 |
|------|--------|------|
| API key 硬编码到源码 | 源码文件 | 代码中无 key 引用，运行时从钥匙串读取；CI 扫描 secret |
| key 泄露到 Git 历史 | Git 仓库 | `.env` 在 `.gitignore`；key 不写入任何文件；pre-commit hook 扫描 |
| key 写入日志/终端 history | 日志/终端 | 日志中 key 脱敏（显示 `sk-***`）；不通过 `export` 传递（进 shell history） |
| key 被其他进程读取 | 进程环境 | 存系统钥匙串（Windows Credential Manager），进程内存中短暂持有，不落盘明文 |
| key 被恶意依赖窃取 | 依赖供应链 | 锁定依赖版本（`pip-audit` 检查） |

**明文风险说明**：系统钥匙串在 Windows 上由 DPAPI 加密，但拥有当前用户权限的进程可读取；文档明确说明此风险。

### 可用性

- Web UI 遵循 Open Design 设计系统，提供一致现代界面
- HITL 确认面板清晰展示 diff（语法高亮）和命令，一键批准/拒绝
- 首次运行引导：无 key 时提示录入，无配置时生成默认配置
- 错误消息用户友好，不暴露技术细节（如 LLM API 错误翻译为"AI 服务暂时不可用"）

### 可观测性

- 每轮迭代记录结构化日志（JSON 格式）：轮次、动作、结果、耗时
- Web UI 实时展示动作历史时间线
- 会话记忆 JSON 文件可离线查看完整过程
- `AGENT_LOG.md` 记录开发过程关键节点（实验要求）

## 5. 系统架构

单体架构，单一 Python 进程，内核与 Web 服务共享内存。

```
┌─────────────────────────────────────────────────────────┐
│  bugfixer 进程                                          │
│                                                         │
│  ┌─────────────┐    WebSocket    ┌──────────────────┐  │
│  │ Web Service │◄──────────────►│  React Frontend │  │
│  │ (Starlette) │    (HITL/状态)   │ (Open Design)   │  │
│  └──────┬──────┘                 └──────────────────┘  │
│         │ 调用                                          │
│  ┌──────▼──────────────────────────────────────────┐    │
│  │            Harness 内核                         │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │    │
│  │  │主循环    │─►│决策解析器 │─►│工具分发器     │  │    │
│  │  │(AgentLoop)│  │(JSON解析)│  │(ToolDispatcher)│  │    │
│  │  └────┬─────┘  └──────────┘  └──────┬───────┘  │    │
│  │       │ │                            │           │    │
│  │       │ ▼                            ▼           │    │
│  │  ┌──────────┐              ┌──────────────────┐  │    │
│  │  │停机判断   │◄───反馈────│反馈校验器        │  │    │
│  │  │(StopCtrl)│              │(PytestParser)    │  │    │
│  │  └──────────┘              └──────────────────┘  │    │
│  │       ▲                            ▲             │    │
│  │       │                            │             │    │
│  │  ┌──────────┐              ┌──────────────────┐  │    │
│  │  │记忆      │              │治理护栏          │  │    │
│  │  │(JSONMem) │              │(Guardrails)      │  │    │
│  │  └──────────┘              └──────────────────┘  │    │
│  └─────────────────────────────────────────────────┘    │
│         ▲                                               │
│  ┌──────┴──────┐                                        │
│  │ LLM 抽象层   │──► OpenAI / Mock                       │
│  │(LLMClient)   │                                        │
│  └─────────────┘                                        │
└─────────────────────────────────────────────────────────┘
```

### 核心组件

| 组件 | 职责 | 依赖 |
|------|------|------|
| `AgentLoop` | 主循环：组织上下文→调LLM→解析动作→分发→回灌→停机判断 | LLMClient, DecisionParser, ToolDispatcher, FeedbackValidator, StopController, Memory, Guardrails |
| `LLMClient` | LLM 抽象层，OpenAI 实现 + Mock 实现 | openai SDK |
| `DecisionParser` | 解析 LLM 返回的结构化动作 JSON | 无 |
| `ToolDispatcher` | 分发动作到具体工具执行 | Tools, Guardrails |
| `Tools` | 6个工具：read_file, write_file, list_dir, grep, exec_cmd, run_test | 无 |
| `Guardrails` | 路径白名单校验 + 命令黑名单 + HITL 状态机 | Config |
| `FeedbackValidator` | 解析 pytest 输出，提取失败信息，分类 | 无 |
| `StopController` | 多条件停机：测试通过/无进展/超时 | Memory |
| `Memory` | JSON 文件会话记忆 | 无 |
| `Config` | YAML 配置加载 | 无 |
| `WebService` | Starlette + WebSocket，Web UI 后端 | AgentLoop |
| `CLI` | 入口，启动 Web 服务 | WebService |

### 数据流（一次迭代）

1. Web UI 提交任务 → WebService 创建 AgentLoop
2. AgentLoop 组织上下文（系统提示 + 历史 + 测试失败信息）→ 调 LLMClient
3. LLM 返回 JSON 动作 → DecisionParser 解析
4. ToolDispatcher 分发 → Guardrails 校验（白名单/黑名单/HITL）
5. 若需 HITL → WebSocket 推送确认请求 → 等待用户批准
6. 批准后执行工具 → 结果回灌
7. 若动作是 run_test → FeedbackValidator 解析输出 → 分类回灌
8. StopController 判断停机 → 若继续则回到步骤 2

## 6. 数据模型

### 主要实体

```python
# 任务配置（用户提交）
class TaskConfig:
    test_node: str          # "tests/test_foo.py::test_bar"
    bug_description: str    # 自然语言 bug 描述
    allow_paths: list[str]  # 允许修改的文件/目录白名单
    project_root: str       # 目标项目根目录

# LLM 响应
class LLMResponse:
    content: str            # LLM 返回的文本（含 JSON 动作）
    raw: dict              # 原始 API 响应

# 决策（解析后）
class Decision:
    thought: str            # LLM 的思考过程
    action: str             # 动作名（read_file/write_file/...）
    action_input: dict      # 动作参数

# 动作（分发前封装）
class Action:
    name: str               # 工具名
    params: dict            # 工具参数
    iteration: int           # 第几轮

# 工具执行结果
class ToolResult:
    success: bool
    output: str             # stdout/内容
    error: str | None       # stderr/错误消息
    exit_code: int | None

# 治理结果
class GuardrailResult:
    allowed: bool
    reason: str
    requires_hitl: bool     # 是否需要人工确认

# HITL 请求
class HITLRequest:
    id: str                 # 请求 ID
    action: Action
    diff: str | None        # 文件变更预览
    command: str | None     # 命令预览
    status: str             # PENDING/APPROVED/REJECTED

# 测试失败
class Failure:
    test_name: str          # "test_foo.py::test_bar"
    error_type: str         # AssertionError/ImportError/...
    file: str | None        # 出错文件
    line: int | None        # 出错行号
    message: str            # 错误消息

# 测试结果
class TestResult:
    passed: bool
    failures: list[Failure]
    raw_output: str         # 原始 pytest 输出

# 停机决策
class StopDecision:
    should_stop: bool
    reason: str             # SUCCESS/NO_PROGRESS/MAX_ITERATIONS
    iteration: int

# 会话记忆记录
class SessionRecord:
    id: str
    task: TaskConfig
    actions: list[Action]   # 动作历史
    results: list[ToolResult]
    test_results: list[TestResult]
    stop_reason: str | None
    created_at: str
    updated_at: str
```

### 关系

- `TaskConfig` 1:1 `SessionRecord`（一个任务一个会话）
- `SessionRecord` 1:N `Action`（会话含多轮动作）
- `Action` 1:1 `ToolResult`（每个动作一个结果）
- `Action` 1:0..1 `HITLRequest`（需确认的动作才有）
- `TestResult` 1:N `Failure`（一次测试可有多个失败）

### 约束

- `allow_paths` 必须非空（至少允许一个文件）
- `test_node` 必须是有效 pytest 节点格式
- `iteration` 从 0 递增
- `HITLRequest.status` 只能从 `PENDING` → `APPROVED`/`REJECTED`（不可逆）

## 7. 凭据与分发设计

### 凭据存储方案

**存储**：系统钥匙串（`keyring` 库）
- Windows: Credential Manager（DPAPI 加密）
- macOS: Keychain
- Linux: Secret Service（需 D-Bus）

**服务名**：`bugfixer`
**账户名**：`openai_api_key`

**录入/更新/清除流程**：

```
首次运行 / bugfixer key set
    │
    ▼
getpass("请输入 OpenAI API key: ")  # 隐藏输入
    │
    ▼
keyring.set_password("bugfixer", "openai_api_key", key)  # 存入钥匙串
    │
    ▼
验证: 调用 OpenAI API 发一个最小请求
    │
    ├─ 成功 → "key 已保存并验证有效"
    └─ 失败 → 提示错误，询问是否仍保存

bugfixer key status
    │
    ▼
keyring.get_password("bugfixer", "openai_api_key")
    │
    ├─ 非 None → "key 已设置 (sk-***...abc)"  # 脱敏显示
    └─ None → "key 未设置"

bugfixer key clear
    │
    ▼
keyring.delete_password("bugfixer", "openai_api_key")
    │
    ▼
"key 已清除"
```

**运行时读取**：AgentLoop 初始化时从钥匙串读取，传入 LLMClient，不记录到日志/记忆/终端。

### 分发设计

**形态**：PyPI 包
**包名**：`bugfixer`
**安装命令**：`pip install bugfixer`
**CLI 命令**：`bugfixer`（启动 Web 服务 + 打开浏览器）

**目标平台**：Windows / macOS / Linux（Python 3.11+）
**CPU 架构**：不限（纯 Python，无原生扩展）

**目标机器安全配置 key 流程**：
1. `pip install bugfixer`
2. `bugfixer key set` → 隐藏输入 key → 存入系统钥匙串
3. `bugfixer` → 启动 Web 服务，浏览器打开 `http://localhost:7777`
4. 在 Web UI 输入失败测试、bug 描述、选择白名单 → 启动修复

**已知限制**：
- 需 Python 3.11+
- Linux 需 D-Bus 运行（Secret Service 依赖）
- 需联网调用 OpenAI API
- 修 bug 目标项目需使用 pytest
- 系统钥匙串在多用户环境下按用户隔离

**CI 构建**：
- GitHub Actions：push 时 `pytest` 跑测试
- 发布到 PyPI：tag 触发 `python -m build` + `twine upload`
- 前端构建：CI 中 `npm run build`，产物打包进 Python 包（`bugfixer/web/static/`）

## 8. 技术选型与理由

| 层 | 技术 | 理由 |
|----|------|------|
| **语言** | Python 3.11+ | LLM SDK 成熟（openai 官方包）；pytest 测试友好；Pydantic 做确定性数据模型；PyPI 分发自然；类型提示 + `match/case` 提升代码质量 |
| **LLM 供应商** | OpenAI（GPT-4o/4.1） | 函数调用能力强，适合修 bug 这种需要工具调用的场景；SDK 成熟稳定；抽象层支持 mock |
| **LLM 抽象层** | 自定义 `LLMClient` 协议 + `OpenAIClient`/`MockLLMClient` 实现 | 不依赖高层 agent 框架；用 `typing.Protocol` 定义接口，可注入 mock 跑确定性单测 |
| **数据模型** | Pydantic v2 | 类型安全验证；JSON 序列化自然；与 OpenAI SDK 兼容；数据模型即文档 |
| **Web 后端** | Starlette + uvicorn | 轻量 ASGI，原生 WebSocket 支持；不引入大框架；harness 内核与 Web 解耦 |
| **前端** | React + Vite + TypeScript | 生态成熟；Open Design 兼容性好；Vite 构建快；TS 类型安全 |
| **设计系统** | Open Design 组件库 | 实验要求；提供一致现代 UI；具体使用的组件在实现阶段调研确定 |
| **测试** | pytest + pytest-asyncio | Python 生态标准；fixture 丰富；可测异步主循环；mock LLM 跑确定性单测 |
| **凭据存储** | keyring 库 | 跨平台访问系统钥匙串；不自己实现加密（用 OS 级安全） |
| **配置** | YAML（PyYAML） | 人类可读可编辑；Python 生态成熟；CLI 参数覆盖 |
| **CLI** | Click | 成熟、子命令自然（`bugfixer key set`）；类型提示友好 |
| **日志** | structlog | 结构化 JSON 日志；便于可观测性 |
| **依赖管理** | uv + pyproject.toml | 现代 Python 依赖管理；锁定版本；`uv` 速度快 |

**不使用的技术及理由**：
- **不使用 LangChain/AutoGen/CrewAI**：实验硬性要求，harness 内核必须自己实现主循环，不能寄生于现成框架
- **不使用 FastAPI**：Starlette 足够，FastAPI 的自动文档等功能对本项目非必需
- **不使用 Docker 分发**：修 bug 需访问本地代码，容器挂载复杂；PyPI 更自然

## 9. 验收标准

### 核心机制验收（mock LLM 可确定性单测）

| 机制 | 验收标准 | 验证方式 |
|------|----------|----------|
| **主循环** | 给定 mock LLM 返回预设动作序列（read→write→run_test），主循环按序执行并停机 | 单测：mock LLM，断言动作序列和停机 |
| **决策解析** | 给定合法 JSON，解析出正确 Decision；给定非法 JSON，返回 DecisionError | 单测：传入合法/非法 JSON，断言结果 |
| **工具分发** | 给定 action 名，分发到正确工具；未知 action 返回 ToolError | 单测：传入各 action，断言分发结果 |
| **治理-路径白名单** | 白名单外写操作被拦截（allowed=False）；白名单内通过 | 单测：构造白名单内外路径，断言结果，无需 LLM |
| **治理-命令黑名单** | `rm -rf /` 等危险命令被拦截；安全命令通过 | 单测：传入危险/安全命令，断言结果，无需 LLM |
| **治理-HITL 状态机** | PENDING→APPROVED 执行动作；PENDING→REJECTED 不执行；超时默认 REJECTED | 单测：模拟状态转换，断言动作执行/不执行 |
| **反馈-测试解析** | 给定 pytest 输出样本，提取正确失败信息并分类 | 单测：传入样本输出，断言 Failure 字段 |
| **停机-成功** | 测试全绿 → StopReason.SUCCESS | 单测：mock 测试通过，断言停机 |
| **停机-无进展** | 连续 3 轮相同修改 → StopReason.NO_PROGRESS | 单测：构造重复动作历史，断言停机 |
| **停机-超时** | 达到 10 轮 → StopReason.MAX_ITERATIONS | 单测：mock 10 轮，断言停机 |
| **记忆** | 写入动作记录后读取，数据一致；文件损坏返回空历史 | 单测：写入读取对比，模拟损坏 |
| **配置** | YAML 加载 + CLI 覆盖；文件不存在创建默认 | 单测：加载/覆盖/默认创建 |

### 端到端验收（真实 LLM）

| 功能 | 验收标准 |
|------|----------|
| **US1 启动任务** | Web UI 提交任务后，harness 开始迭代，UI 显示进度 |
| **US2 自主修复** | 给定一个简单 Python bug（如 off-by-one），harness 在 10 轮内修复，测试通过 |
| **US3 范围围栏** | LLM 尝试改白名单外文件时，被拦截，Web UI 显示拦截原因 |
| **US4 HITL 确认** | 每个写操作/危险命令在 Web UI 显示 diff/命令，用户批准后执行，拒绝后跳过 |
| **US5 反馈修正** | 测试失败后，LLM 基于结构化失败信息修正代码（非原始输出） |
| **US6 停机报告** | 停机后 Web UI 展示结果（成功/失败原因）和完整动作历史 |
| **US7 凭据安全** | `bugfixer key set` 隐藏输入存入钥匙串；`status` 不回显明文；`clear` 清除 |

### 治理维度深入验收（主要贡献）

| 验收点 | 标准 |
|--------|------|
| 多层防御 | 路径白名单 + 命令黑名单 + HITL 三层独立可测，移除 LLM 后全部可单测验证 |
| HITL 状态机 | 状态转换确定性，超时/拒绝/批准分支均有单测覆盖 |
| 拦截不依赖 LLM | `guardrail(Action)` 函数直接判定，不调用 LLM，每次结果相同 |

## 10. 风险与未决问题

### 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| **LLM 返回非合法 JSON** | 决策解析失败，循环中断 | 解析失败不直接停机，将错误信息回灌上下文让 LLM 重试；连续 3 次解析失败触发停机 |
| **LLM 不遵从系统提示** | 返回非预期动作格式 | 系统提示明确约束格式 + few-shot 示例；解析层兜底错误处理 |
| **pytest 输出格式变化** | 反馈解析器失效 | 解析器基于 pytest 标准输出格式（`FAILED`/`ERROR` 标记），版本兼容性测试；解析失败返回 `ParseError` 不崩 |
| **OpenAI API 限流/超时** | 循环卡住 | 重试 3 次（指数退避）；超时后抛 `LLMError`，Web UI 提示用户 |
| **WebSocket 断开时 HITL 待确认** | 动作卡在 PENDING | 超时 5 分钟默认 REJECTED；断开时推送状态恢复 |
| **白名单路径解析歧义** | 相对路径/符号链接绕过白名单 | 白名单规范化为绝对路径（`Path.resolve()`）；符号链接解析后校验 |
| **keyring 在 Linux 无 D-Bus** | 凭据无法存储 | 文档明确依赖；降级方案：提示用户安装 `gnome-keyring` 或用 `.env`（明文风险警告） |
| **Open Design 组件不满足需求** | 前端开发受阻 | 实现阶段先调研组件库；不满足时用自定义组件遵循设计 token |
| **mock LLM 测试与真实 LLM 行为差异** | 单测通过但真实运行失败 | 端到端测试用真实 LLM 验证核心路径；mock 测试覆盖机制逻辑而非 LLM 智能 |

### 未决问题

1. **Open Design 具体组件**：实现阶段需调研 `nexu-io/open-design` 仓库，确定可用组件（按钮、表单、diff 展示、时间线等），SPEC 中标记为"实现阶段确定"。
2. **系统提示词内容**：提示词属于"内容物"不计入 harness 实现，但影响真实运行效果。实现阶段编写，包含工具描述、动作格式约束、few-shot 示例。
3. **失败分类的修复策略提示**：是否为每类失败提供修复策略提示（如 ImportError → "检查导入路径"）。初版只分类回灌，策略提示作为可选增强。
4. **多文件 bug**：当前设计聚焦单测试节点单白名单，复杂多文件 bug 暂不支持。后续可扩展。
