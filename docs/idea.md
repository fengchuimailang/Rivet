我要做一个面向 RISC-V 芯片设计与验证的 Agent 产品体系，定位对标 Cadence ChipStack 这类“芯片设计超级 Agent”，但采用开源技术栈，可私有化部署，并可扩展为系列产品（CLI、IDE、后续云端）。总体架构本地优先；MVP 首先支持用户配置的云端模型，不承诺离线运行，本地模型和完全离线能力后续再加入。

一、核心定位
- 领域：RISC-V RTL 设计、验证、调试、形式化、基础实现流程辅助
- 对标能力：类似 ChipStack 的多 Agent 协作 + 设计意图/层次/规格的结构化认知（Mental Model）
- 差异化：全面基于开源 EDA，可私有化、可本地跑，不绑定商业 EDA 许可
- 用户：芯片设计/验证工程师、RISC-V 团队、学生与开源硬件开发者

二、要解决的核心问题
- Spec → RTL → 仿真 → 形式化 → 调试 的长链路、多工具、强迭代
- 工具链碎片化（Verilator / Yosys / SymbiYosys / cocotb / riscv-formal 等）
- 上下文易爆炸、任务周期长（仿真/形式化可能很久）
- 需要人机协同：Agent 可改代码、跑工具，但关键写操作与危险命令需可控审批

三、推荐技术底座
1) Agent 框架：Deep Agents（langchain-ai/deepagents，建议 0.7.x+）
   - 内置 filesystem、subagents、context 管理、skills、memory
   - 支持 Async Subagents：长后台任务（非阻塞、可查询、可中途更新、可取消）
   - 适合做 Mental Model 持久化 + 多专业子 Agent 编排

2) 开源 EDA 工具链（领域工具层）
   - 仿真：Verilator + cocotb（或同类）
   - 综合/逻辑：Yosys
   - 形式化：FIFO 等通用 RTL 使用 SymbiYosys；RISC-V 核心使用 riscv-formal（RVFI 等）
   - 可选：OpenLane/OpenROAD（后端/实现向，后期再加深）
   - RISC-V 相关：riscv-dv、开源核心（Rocket/CVA6 等）作为验证对象或模板

3) 模型层
   - MVP：支持用户配置的云端模型，以 OpenAI-compatible provider 接入
   - 后续：增加 Ollama、vLLM 等本地 provider，逐步支持完全离线运行
   - provider 能力由 Rivet 定义最小契约：工具调用、结构化输出、流式响应、取消、超时、重试及请求元数据记录；兼容接口不代表各服务行为完全一致

4) Backend（文件与执行）
   - Agent runtime 不直接暴露通用 shell backend；Agent 只能调用 Rivet 定义的文件读写能力和结构化 run_job 工具
   - root_dir 限定在工程根目录；路径校验用于防止越界，但不视为 OS 级隔离
   - 需要跨会话记忆时用 CompositeBackend（/workspace 真实磁盘，/memories 持久化等）
   - Deep Agents 作为可替换的 Agent runtime adapter，不是 Rivet 的领域协议边界

四、Agent 架构设计（对标 ChipStack，但开源实现）
1) Mental Model（结构化设计认知）
   - 用 filesystem / knowledge graph / JSON 等持久化：
     规格意图、模块层次、接口、约束、验证计划、已知问题、运行产物索引
   - Agent 不把所有细节塞进 prompt，而是读写 Mental Model + 按需读工程文件

2) 多 Agent 分工（示例）
   - Super/Orchestrator：理解目标、拆任务、调度、汇总
   - RTL Agent：生成/修改 SystemVerilog/Verilog
   - TB/验证 Agent：cocotb、测试计划、覆盖率导向
   - Formal Agent：SBY、riscv-formal、属性与假设
   - Debug Agent：日志、波形线索、失败归因、最小复现
   - （可选）SoC / Signoff 向 Agent：后期扩展

3) 长任务
   - 用 Deep Agents Async Subagents 跑长时间仿真/形式化
   - 主 Agent 保持可对话；支持 check / update / cancel
   - 完成后以摘要写回 Mental Model 与报告文件

五、产品形态（系列产品，同一 Agent Core）
1) CLI / TUI：工程师脚本化、CI、无 GUI 场景
2) VS Code 体系（重点）
   - 短期：VS Code Extension + 本地 Agent Sidecar（推荐）
   - 中期：深度 IDE 体验（类 Cursor）：Chat、Inline Edit、多文件 diff、审批流、终端/任务集成
   - 原则：IDE 负责感知与交互；Deep Agents Runtime 负责推理与执行
3) 后续：Web/团队版、可选云端 Runtime（协议先预留）

六、IDE 集成原则（类 Cursor）
- 扩展/魔改 IDE 不直接重跑 Agent 主循环，而是连本地 Sidecar Runtime
- 上下文桥：当前文件、选区、诊断、Git、终端摘要、工作区根
- 工具网关：apply_edit、diagnostics、terminal、workspace search 等
- 写操作默认 Human-in-the-loop（diff 预览后 Accept/Reject）
- 事件流协议稳定化（message / tool / file.changed / interrupt / async.task）
- 一套 Agent Core + 多 Adapter（VS Code / CLI / Web）

七、安全与工程约束
- 限制 root_dir；路径约束不替代操作系统隔离
- Agent 不获得任意 shell；LocalRunner 只接受固定枚举 job（lint/compile/test）和类型化参数，不接受任意命令字符串
- Runner 固定工作目录和环境变量 allowlist，设置超时与输出上限，支持取消子进程组，并区分正常退出、信号、超时和取消
- 工作区写入经 diff 预览和明确审批；危险操作与批量写入强制审批
- 大输出落盘，不灌爆上下文
- 架构本地优先；MVP 使用云端模型，因此不承诺离线。密钥与代码尽量不出域，并明确告知用户发送给 provider 的数据范围
- Deep Agents 版本在实现前精确锁定，并通过 Rivet adapter 和 contract tests 隔离其 API；关注 backend 与 async subagent 行为

八、成功标准（阶段性）
- Phase 1：给定 RTL 模块需求，能 Spec→RTL→Verilator/cocotb 跑通，并在 CLI 中可交互修改
- Phase 2：FIFO 通用属性可用 SymbiYosys 作为后台长任务验证；失败可辅助定位
- 后续 RISC-V 核心 benchmark 再接入 riscv-formal/RVFI
- Phase 3：Mental Model 跨会话有效；多子 Agent 稳定协作；加入 VS Code，产品化权限与 diff 体验接近 Cursor 可用水平

九、明确不做（初期）
- 不复制 ChipStack 的闭源商业 EDA 深度绑定
- 不把完整 Place&Route/签核流水线作为第一目标
- 不做“无审批自动大改生产库”的完全无人值守（至少默认关闭）

请在后续讨论/设计/编码中，始终以上述定位为准：
以 Deep Agents 为 Agent 底座，以开源 EDA 为工具层，以 Mental Model + 多 Agent 为架构，以 CLI + VS Code（类 Cursor）为产品入口，服务 RISC-V 设计验证的长链路人机协同。

十、已确定的 MVP 定义
1) 目标用户与运行环境
   - 首批用户：专业芯片设计/验证工程师
   - MVP 仅支持 Linux x86_64
   - 默认使用用户本地安装的开源 EDA 工具；不要求 Docker 或容器环境
   - 模型先支持用户配置的云端模型，抽象为 OpenAI-compatible provider；后续可增加 Ollama、vLLM 等本地 provider
   - 许可证暂定 MIT
   - 模型请求可能访问云端；CLI 必须展示 provider、模型和将发送的数据范围，并避免默认上传完整工作区或密钥

2) 首个端到端场景：单时钟同步 FIFO
   - 输入：自然语言需求
   - 输出：参数化 Verilog RTL、cocotb 测试、结构化 Spec/Mental Model、待审批 patch、可复现运行报告
   - FIFO v1 约束：单时钟、同步复位、参数 DATA_WIDTH/DEPTH、write/read enable、full/empty；双时钟异步 FIFO 不属于 MVP
   - FIFO 是用于验证 RTL Agent 闭环、执行器和审批协议的通用基线，不代表最终 RISC-V 领域能力
   - 规格需明确 DEPTH 是否要求 2 的幂、DEPTH=1 支持情况、合法参数范围、复位极性/持续周期、输出时序、空读/满写处理，以及满/空边界上的并发读写行为
   - 验证重点：复位、空满边界、并发读写、随机序列和参数化配置
   - CSR 与总线模块作为后续 benchmark，不阻塞 FIFO MVP

3) Benchmark 策略
   - 目前没有一个公开标准集直接覆盖“自然语言 Spec → FIFO RTL/测试 → 工具运行 → Agent 修复”完整闭环；Rivet 维护版本化、自有 FIFO benchmark 集作为 MVP 主评估集
   - benchmark 包含固定 Spec 变体、参数组合、独立验收测试、参考模型、预置故障变体及 manifest；验收测试不能由 Agent 生成的测试替代
   - 初始变体覆盖基础 FIFO、DEPTH=1、非 2 的幂深度（若规格支持）、不同 DATA_WIDTH、复位边界、空满边界、并发读写、短/长随机序列和非法操作
   - 预置故障覆盖指针回绕、full/empty 更新、复位、满写/空读、并发读写计数等常见错误，用于评估 Debug 与修复能力
   - 公开项目仅作设计、验证和工具链参考；仅在许可证及接口兼容时复用其代码或测试。RISC-V 核心 benchmark 在 FIFO 闭环稳定后单独引入
   - 记录首次通过率、最多 5 轮修复通过率、平均修复轮次、人工审批次数、验收测试被修改次数及失败报告可定位性；先建立基线，再据实确定量化退出门槛
   - 参考项目：HDLBits（小型 RTL 题目）、cocotb（testbench 与仿真集成）、verilog-axis（FIFO/流接口验证）、Ibex（RISC-V 项目验证/CI 组织）、SymbiYosys examples（形式化任务与反例）、riscv-formal（RVFI 核心验证）、riscv-dv（指令级随机验证）

4) 自主修复协议
   - 每个任务最多执行 5 个修复轮次
   - 每轮只产生一个逻辑变更集（patch）；任何工作区文件改动均须用户预览并明确批准后才可写入
   - change 记录包含 change ID、基于的源码 tree hash、Spec revision、文件清单、unified diff、生成模型/配置摘要及验证状态；审批后应用的内容必须与获批 diff/hash 一致
   - 变更状态至少包括 proposed、approved、applied、verified、rejected、failed、superseded；应用前检测工作区是否相对生成快照发生冲突
   - Agent 修改验收测试、Spec 或 runner 配置时必须在 diff 中单独显著呈现并单独审批；MVP 默认保护 benchmark 验收测试和 runner
   - 获批后，编译、lint 和测试可自动执行；下一轮修改仍须单独审批
   - 成功条件：所有验收测试通过、无新增 lint/编译问题、Spec 到实现和验证的追溯关系完整
   - 失败条件：达到轮次上限、关键需求存在歧义、或工具环境无法满足项目声明的版本要求；必须输出已验证事实、未决问题和可复现证据

5) 本地 EDA 环境与执行安全
   - CLI 提供 rivet doctor，检测 verilator、yosys、python、make 和 cocotb 的路径、版本及可用性
   - 项目通过 rivet.toml 声明工具命令、最低版本、已验证版本和测试入口；不得将本机绝对路径或版本假设硬编码到 Agent prompt
   - 维护已验证的工具组合。未在组合内但满足最低版本的环境允许尝试运行，但必须明确标为“未经验证”
   - MVP 的执行器为 LocalRunner。它只能执行固定枚举的 compile/test/lint job 和类型化参数，不能接受任意命令字符串；Agent 不直接获得任意 shell 能力
   - 每个 job 固定工作目录和环境变量 allowlist，设置超时与输出上限，可取消整个子进程组，并分别记录正常退出、信号、超时和取消
   - 日志、波形、编译缓存和结构化结果统一写入 .rivet/runs/<run-id>/，不得污染源码目录；每次运行记录源码 tree hash、Spec revision、job schema 版本、工具和 Python 依赖版本、结构化 job 参数、退出码/状态、耗时和产物索引
   - Agent 任务报告还记录 provider/模型、Agent runtime 与配置版本、change ID；不默认保存完整 prompt 或上传完整工作区
   - 后续可以增加 ContainerRunner 或远程 worker，但其 job 协议和产物布局必须与 LocalRunner 兼容

6) Spec 与 Mental Model
   - Spec 是人主导的外部行为契约，描述接口、时序、复位、参数、边界/错误行为和验收条件，回答“应该实现什么”
   - Mental Model 是 Agent 从 Spec、源码和运行证据持续维护的当前工程认知，描述模块层次、信号角色、已验证性质、覆盖情况、失败历史、未决假设及其置信度，回答“当前系统是什么状态、为什么如此判断”
   - Spec 是外部行为的规范性来源；Mental Model 记录当前工程认知、推断和证据，不得覆盖或修改 Spec 要求，二者不可合并
   - Spec requirement 使用稳定 ID；验证计划显式引用 requirement ID。Spec revision 变化时，相关测试、模型结论和运行结果标记为 stale，重新验证后才能恢复为已验证
   - Mental Model 中可审查的结论应记录 claim ID、来源类型、来源引用（文件/行号、测试名或 run ID）、置信度、观测时间和失效条件
   - 两者都必须对工程师可读、可编辑和可审查，先使用版本化 YAML/JSON，不在 MVP 引入知识图谱
   - 初始项目布局：
     .rivet/spec.yaml：规范化需求与验收标准
     .rivet/model.yaml：模块、接口、关键语义、推断与置信度
     .rivet/verification.yaml：测试/断言计划及到 Spec 的追溯关系
     .rivet/runs/：运行日志、波形、结果和产物索引
     .rivet/changes/：待审批 patch 与验证报告

7) MVP 产品边界
   - 只提供 CLI，不在 MVP 开发 VS Code Extension；CLI 的任务、事件和审批协议必须为后续 Sidecar/IDE 复用而设计
   - 优先实现单编排 Agent + 受限的设计理解、验证、调试任务；只有并行、上下文隔离或权限隔离存在明确收益时才拆分为多 Agent
   - Deep Agents 用作可替换的 Agent runtime adapter；领域 job、执行器、数据 schema、事件和审批协议属于 Rivet 自身边界，不能被框架 API 直接绑定
   - 不在 MVP 实现完整 SoC、Place-and-Route、签核、任意 shell、无人审批写入或离线模型支持

十一、开发阶段与退出标准
1) Phase 0：可重复的非 Agent 基线
   - 建立 Rivet 自有版本化 FIFO benchmark；以确定性命令完成 lint、Verilator 编译和 cocotb 独立验收测试
   - 定义统一 RunResult：状态、退出码/信号、耗时、日志、波形/产物路径、源码 tree hash、工具版本和验证环境状态
   - 完成标准：rivet doctor 和 benchmark 在已验证版本组合中可重复运行，人工可由报告定位失败

2) Phase 1：CLI 单 Agent 闭环
   - 实现自然语言需求到 Spec、RTL/测试 patch、审批、自动验证和最多 5 轮修复的闭环
   - 实现 YAML/JSON 的 Spec、Mental Model、验证追溯和运行报告
   - 完成标准：固定 FIFO benchmark 集能在受控审批下完成生成和多轮修复评估；实现通过独立验收测试，Agent 不能靠修改验收测试制造成功，并保留完整可复现证据

3) Phase 2：形式化与后台任务
   - FIFO 接入 SymbiYosys 通用安全/活性属性；形式化任务可查询、取消、恢复并保存 counterexample
   - 后续 RISC-V 核心接入 riscv-formal/RVFI
   - Debug 能基于落盘日志、波形和反例建立假设、生成最小复现

4) Phase 3：IDE 与产品化
   - 增加 VS Code Extension + 本地 Sidecar，提供任务面板、diff 审批、诊断定位、运行日志和波形/反例链接
   - 增加可选容器/远程执行器、团队共享策略和本地模型 provider
