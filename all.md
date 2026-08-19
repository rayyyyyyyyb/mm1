# R0 全过程记录

> 本文件按时间顺序记录 OV-OrthKD R0 阶段的全部实质操作、命令目的和结果。更新本日志本身不再递归记录。

## 2026-08-19

1. 收到任务：连接 `LXT@100.119.122.101`，后续实验使用该机器的 RTX 5090。
2. 使用本机 OpenSSH 进行公钥登录验证；SSH 成功，远端主机为 `DESKTOP-LPN6MT3`，用户为 `desktop-lpn6mt3\lxt`。
3. 查询远端 GPU：设备 0 为 NVIDIA GeForce RTX 5090，总显存 32607 MiB，首次检查时空闲 31444 MiB，驱动 610.88。
4. 确认远端系统为 Windows NT 10.0.26200.0。
5. 在本地仓库中定位“扩刊”目录；发现唯一任务书 `MM26_OVORTHKD_R0_REPRODUCTION_IMPLEMENTATION_TASK.md`，共 1671 行、62820 字节。
6. 以 UTF-8 分段完整阅读任务书，确认本阶段仅实施 R0 paper-faithful reproduction hardening，不实施 VP-AdaOrthKD 扩刊机制，不下载完整数据、不导出完整教师工件、不启动完整训练。
7. 检查 Git：当前分支 `main`，HEAD 与任务书基线一致，为 `dca9f052fbe4a1e9d7982f24bdcec3edf1363fd4`；`扩刊/` 当时为未跟踪目录。
8. 逐项读取并审计现有模型、损失、数据集、训练、preflight、评价、教师导出、效率、环境脚本、配置、测试和 README。
9. 确认现有实现存在任务书列出的主要差距：定位头读取共享特征、文本损失公式不一致、伪造弱教师 logits、缺工件静默置零、随机性与证据链不足、评价与导出截断不完整、5090 环境脚本无 cu128。
10. 只读检查远端运行环境：SSH 会话中没有可用 Python、Git、WSL 或 Bash；`winget` 可用。
11. 检查远端磁盘：C: 空闲约 1689.7 GB，D: 空闲约 722.5 GB，E: 空闲约 5729.4 GB。
12. 提出并获准采用本地“扩刊”内隔离开发目录、远端 E: 盘原生 Windows Python 环境、运行产物回收到“扩刊”的方案。
13. 收到追加要求：在本地“扩刊”文件夹完成本阶段全部任务和代码，完成后将完整文件夹上传到对应 GitHub 仓库；创建并持续维护本 `all.md`，不再询问，直接执行。
14. 用户确认相关运行环境可直接在 5090 上搭建。执行边界冻结为：本地“扩刊”保存代码、文档及回收后的实际产物；5090 保存 Python、Git、CUDA/PyTorch venv 与下载缓存，环境目录不回传、不提交。
15. 读取 `superpowers:using-git-worktrees` 与 `superpowers:writing-plans` 工作流。确认实施前必须建立隔离工作区、验证基线，并在写代码前保存设计与逐项实施计划；用户已明确要求直接执行，因此不再增加人工确认停顿。
16. 执行 Git 隔离状态检查：当前是普通主工作区而非 linked worktree，分支为 `main`，仅有一个工作树，HEAD 为基线 `dca9f052...`；目标 `扩刊/OV-OrthKD-R0` 尚未被 Git 忽略。
17. 检查根仓库 `.gitignore` 与 `.git/info/exclude`：已有常规 Python、环境、数据和输出忽略规则，但没有“扩刊”隔离目录规则。为避免改动并提交主分支 `.gitignore`，决定仅在本机 `.git/info/exclude` 忽略 `扩刊/OV-OrthKD-R0/`；任务书与 `all.md` 仍保持可见。
18. 已向本机 `.git/info/exclude` 添加 `/扩刊/OV-OrthKD-R0/`。该规则只保护本地嵌套 worktree，不改变项目版本历史，也不会隐藏 `扩刊/all.md` 或任务书。
19. 创建 linked worktree `扩刊/OV-OrthKD-R0`，新分支为 `repro/r0-paper-faithfulness`，起点精确为 `dca9f052fbe4a1e9d7982f24bdcec3edf1363fd4`。检查结果：新工作树干净，根工作树仍停留在 `main`。
20. 将已批准设计写入 `扩刊/OV-OrthKD-R0/docs/superpowers/specs/2026-08-19-r0-paper-faithfulness-design.md`。设计冻结了双实现模式、损失语义、严格数据、确定性、full-run 阻断、证据链、评价、审计、教师身份、5090 Windows 环境和六项归档阻塞事实。
21. 自审设计文档：占位符扫描为 clean，`git diff --check` 无格式错误；当前 worktree 仅新增 `docs/`，未发现设计内冲突或越过 R0 边界的内容。
22. 使用 `superpowers:writing-plans` 创建 `docs/superpowers/plans/2026-08-19-r0-paper-faithfulness.md`。计划分为八个顺序任务：5090 环境与基线、双路径模型/损失、严格数据与确定性、训练安全与证据链、评价、审计工具、完整 R0 验证、最终日志/单提交/GitHub 上传。
23. 自审 526 行实施计划：占位符扫描 clean，任务书要求的 17 个核心文件全部被计划覆盖，接口命名在相邻任务间一致，`git diff --check` 通过。
24. 选择 inline execution（用户要求直接执行，且未授权多代理），读取 `superpowers:executing-plans` 与 `superpowers:test-driven-development`。实施约束为：每个行为先写测试并在 5090 上观察预期失败，再写最小实现、观察通过并回归；所有任务结束后再进入分支收尾流程。
25. 阅读 TDD 配套 `writing-good-tests.md`：测试必须命名其捕获的真实破坏、使用独立手算期望、验证真实行为而非源码字符串或 mock 本身，并在收尾时做变异思考检查。
26. 批判性复核实施计划后未发现阻止开工的歧义；创建八项执行清单并将“建立 5090 环境与验证未修改基线”标记为进行中。
27. 核验官方运行来源：Python 官方 3.11 发布页提供 Windows 64-bit 安装；PyTorch 官方 Get Started 页确认 Windows 支持 Python 3.10–3.14，并列出 CUDA 12.8 计算平台与官方 wheel 索引。决定在 5090 使用 Python 3.11 和 `https://download.pytorch.org/whl/cu128`，不使用测试/nightly 或第三方镜像。来源：`https://www.python.org/downloads/release/python-3119/`、`https://pytorch.org/get-started/locally/`。
28. 首次通过 `winget` 在 5090 安装 `Python.Python.3.11` 失败，退出码 1。winget 已解析到官方 Python 3.11.9 安装包，但其临时下载文件被另一个进程占用，报错 `The process cannot access the file because it is being used by another process`；尚未修改代码，转入系统化诊断。
29. 读取 `superpowers:systematic-debugging`。针对 winget 文件锁先执行根因调查：检查是否已有安装进程、临时目录状态、安装结果和可重复性；确认根因后才做单一修复。
30. 根因调查第一轮：Python 实际未安装；远端仍残留 PID 21076 的 `winget` 进程，它独占持有报错路径中的 0 字节临时文件。错误不是 Python 安装器本身，而是前一 winget 调用尚未正常退出或已挂起并自锁临时下载目标。
31. 对 PID 21076 做 5 秒双快照：CPU 始终 0.890625、句柄始终 716、临时文件始终 0 字节且最后写入时间不变，确认进程已挂起而非继续下载。单一修复假设：终止该挂起进程并删除其精确的 0 字节临时文件后，winget 可重新创建下载目标。
32. 执行单一修复：仅终止已确认挂起的 winget PID 21076，并删除其精确的 0 字节临时下载文件。验证 `ProcessRunning=False`、`TempFileExists=False`；删除对象没有有效内容且不可恢复，但不涉及用户数据。
33. 重新运行同一 winget 安装后连续约三分钟无输出，停止本地等待并检查远端：新 PID 15316 的 winget 再次保持低且不变的 CPU，Python 仍未安装，临时目标再次停在 0 字节。说明清理旧锁不是根因；模式指向 winget 在非交互 SSH 会话中的下载层挂起。下一项最小验证是仅对官方 python.org 安装包做 HTTPS HEAD 请求，区分网络问题与 winget 问题。
34. 远端 `curl.exe -I` 请求官方 Python 3.11.9 x64 URL 成功返回 HTTP 200、Content-Length 26216840，证明到 python.org 的 HTTPS 网络正常，问题局限在 winget 非交互下载层。
35. 从 Microsoft 官方 `winget-pkgs` 清单核对 Python 3.11.9 x64 安装包 SHA256：`5EE42C4EEE1E6B4464BB23722F90B45303F79442DF63083F05322F1785F5FDDE`；Python 3.11 官方 Windows 文档确认 `/quiet InstallAllUsers=0 TargetDir=... Include_test=0` 的静默自定义目录语义。决定绕过已复现挂起的 winget 下载层，直接下载官方安装包、校验 SHA256 后静默安装到 E: 盘。
36. 首次组合“停止挂起进程、清理临时文件、下载并安装”的远端命令在本机工具策略层被拒绝，未发送到 5090、没有产生远端变更。调整为更小步骤：不再删除 winget 临时目录，单独停止已确认挂起的进程；官方安装包使用不同的 E: 路径并直接调用。
37. 单独终止第二个已确认挂起的 winget PID 15316，验证 `ProcessRunning=False`。保留其临时目录不动。
38. 将官方下载与执行拆开后，远端 `curl` 在 300 秒上限内仅收到 637766/26216840 字节（约 2.4%），退出码 28；未执行安装器，部分文件不视为有效。证据表明 5090 到 python.org 的大文件传输极慢，而本地到 5090 的 Tailscale SSH 已稳定。下一最小路径是本地从同一官方 URL 下载并校验同一 SHA256，再通过 SCP 覆盖远端部分文件；Python 最终仍只安装在 5090。
39. 本地同一官方 URL 的 300 秒下载也超时，仅收到 5782342/26216840 字节，退出码 28；本地约 19 KB/s，虽快于远端但仍异常。未上传、未执行该部分文件。根因更新为当前外网到 python.org 的大文件带宽瓶颈，而非单机问题；先搜索本地/远端现有 Python 与 PyTorch wheel/cache，优先复用可信现有资产，再决定是否断点续传。
40. 本地环境盘点：存在可直接运行的官方 Python 3.11.9 于 `C:\Users\lwz20\AppData\Local\Programs\Python\Python311`；完整目录因第三方包达到 2171.5 MB，但可排除 `Lib/site-packages` 后迁移基础解释器并在 5090 重新创建 venv。本地 Python 3.11 没有 torch，pip cache 也没有 torch wheel；Anaconda 仅有 `torch 2.10.0+cpu`、`torchvision 0.25.0` 且无 torchaudio，不可作为 5090 CUDA 环境。默认 Anaconda Python 导入 torch 还触发重复 OpenMP runtime 错误，因此不复用该环境。
41. 从本地官方 Python 3.11.9 安装中排除 `Lib/site-packages`、标准库测试、IDLE 与 Tcl/Tk，生成纯基础运行时归档。原始基础文件 99.6 MB/2164 个，ZIP 为 29.0 MB，SHA256 `B388DBCB6FD82A2B88A5CE3CBB3B26B65186D277A5401C59E7EA001744C63E16`，检查确认不含 site-packages。归档位于本机临时目录，不在项目或最终产物内。
42. 通过 SCP/Tailscale 将 29.0 MB Python 基础归档上传到 `E:\OV-OrthKD-R0\installers\python311-base.zip`，耗时 41.11 秒，传输退出码 0。
43. 5090 重新计算归档 SHA256，精确匹配 `B388DBCB...C63E16` 后才解压。基础解释器 `E:\OV-OrthKD-R0\env\Python311\python.exe` 成功运行 Python 3.11.9；使用内置 ensurepip 安装 pip 24.0/setuptools 65.5.0，并成功创建干净 venv `E:\OV-OrthKD-R0\env\.venv`。venv Python 3.11.9、pip 24.0，退出码 0。
44. 从 5090 的 venv 查询 PyTorch 官方 cu128 索引成功，退出码 0；可用稳定版本包括 `2.11.0+cu128` 至 `2.7.0+cu128`，最新为 `2.11.0+cu128`。决定安装稳定 `torch 2.11.0+cu128` 与同索引匹配的 torchvision/torchaudio。
45. 启动 5090 官方 cu128 pip 安装后约十分钟无流式输出，停止本地 SSH 等待句柄并只读检查。远端安装并未终止：venv wrapper PID 3964 与基础 Python PID 23148 仍在运行，后者累计写入约 787 MB；torch/vision/audio 尚未进入已安装状态。另发现用户目录已有 uv 管理的 CPython 3.11 和两个与本任务无关的 pip 进程（`smc_gate1_env`、uv Python），不触碰这些进程。下一步对本任务 PID 做 I/O 双快照判断进度，不启动重复安装。
46. 对本任务 PID 23148 做 5 秒双快照：CPU 从 17.21875 增至 17.375，写入字节从 796480693 增至 798385333，证明 pip 正在推进而非挂起；torch 尚未安装完成。保留该后台进程继续下载，不启动重复 pip；同时进行不占公网带宽的本地 Git 打包与源码上传准备。
47. 本地 Git 盘点：`C:\Program Files\Git\cmd\git.exe` 为 Git for Windows 2.53.0.windows.2，完整安装 398.5 MB/9302 文件。决定迁移该已验证安装的运行组件到 5090，而不占用当前受限公网连接重新下载 Git。
48. 将 Git for Windows 排除设备节点、临时目录、手册与文档后打包为 135.7 MB ZIP，SHA256 `D86B9448046D420EBF4200A8D8E66EEB49A1DACB018FDCF61E5FF2B2A9C61096`，归档内容确认包含 `cmd/git.exe`。文件位于本机临时目录，不进入项目。
49. 使用 `git archive` 从精确基线 `dca9f052...` 生成未修改源码包 `repo-baseline.zip`，大小 63.5 KB，SHA256 `6BE69531DFEEE7C9F78B0952D9C55F1A72006DA83C1DDCAC32CF1E438FFB15D5`。该包不含当前新增设计/计划，用于 5090 基线测试。
50. 上传基线源码包到 5090，SCP 退出码 0；远端复算 SHA256 完全匹配后解压到 `E:\OV-OrthKD-R0\repo`。检查得到 48 个文件且 `requirements.txt` 存在，未修改基线代码已就位。
51. 再次检查本任务 PyTorch 安装：PID 23148 累计写入已从约 798 MB 增至约 903 MB，仍在推进；torch/vision/audio 尚未完成安装。继续保留单一后台安装进程。
52. 通过 SCP 上传 135.7 MB Git 归档到 5090，耗时 92.61 秒、退出码 0。远端复算 SHA256 精确匹配 `D86B9448...C61096` 后解压到 `E:\OV-OrthKD-R0\env\Git`；`cmd\git.exe --version` 返回 `git version 2.53.0.windows.2`，退出码 0。
53. PyTorch 安装进度检查：本任务 PID 23148 写入量已增至约 1.585 GB，进程仍在运行，包尚未登记为已安装；传输速率已明显提升，继续等待。
54. 为远端运行证据链创建基线 Git bundle，验证包含完整历史与 `refs/heads/main -> dca9f052...`。bundle 52.4 KB，SHA256 `8C2AEEC100E618E5C1000A504C10EA6DC95068F6E428BC5D7F4FE281CCB7DCE7`。
55. 上传并在 5090 校验 Git bundle 后，于 `E:\OV-OrthKD-R0\repo` 初始化 `repro/r0-paper-faithfulness` 仓库，使用 mixed index reset 关联基线而不覆盖工作文件；远端 HEAD 为 `dca9f052...`，status 干净，origin 设置为 `https://github.com/rayyyyyyyyb/mm1`。
56. 30 秒进度观察中 PyTorch 安装写入量从约 1.716 GB 增至 1.744 GB，进程持续推进；包仍未登记。官方 wheel HEAD 显示 `torch-2.11.0+cu128-cp311-win_amd64.whl` 大小为 2753148611 字节（约 2.56 GiB），因此当前仍处于主 wheel 下载阶段。
57. 后续两次只读观察显示写入量依次增至约 1.801 GB 和 1.816 GB，PID 23148 持续存在；未启动重复下载或安装。
58. 再等待 55 秒后写入量增至约 1.887 GB，包仍在下载。为不空等，在不改生产代码的前提下开始按 TDD 编写 Task 2 的失败测试；这些测试必须等远端原基线先通过后才执行 RED。
59. 在隔离工作树新增 `tests/test_paper_faithfulness.py`，为 Task 2 写入尚未执行的 RED 测试：覆盖 camera-ready/legacy 双路径、定位头必须读取 decision projection、映射余弦文本 BCE、禁用 logits 时可省略教师 logits、必需工件与有效 mask 严格失败、`cos²(decision,audio)` 正交项及损失模块只能拥有教师侧 projector。此时未修改任何生产代码；按证据顺序，先等待 5090 环境完成并运行未修改基线，再执行这些测试确认预期失败。
60. 首次远端 PyTorch 状态复查命令因 SSH 到 PowerShell 的引号被剥离而失败，退出码 1；它仍确认 PID 23148 存在，但 `pip show` 的参数被错误解析，不能据此判断包状态。未改变远端环境或代码，改用在远端写入临时 `.ps1` 状态脚本后再执行，避免嵌套引号歧义。
61. 尝试在工具编排层直接生成 PowerShell `-EncodedCommand` 时，运行时不提供 `btoa`，脚本在建立 SSH 前即以 `ReferenceError` 终止；远端没有执行任何命令、没有状态变化。改为使用内嵌的标准 Base64 编码实现生成同一只读状态命令。
62. 使用 UTF-16LE Base64 编码后成功执行远端只读状态命令：任务 Python PID 23148 仍在运行，累计 CPU 37.59375 秒；`pip show torch torchvision torchaudio` 退出码 1，三包尚未登记为已安装。`Get-Process` 本次未返回写入计数字段，因此不能从该字段判断瞬时进度；保留唯一安装进程，继续做本地测试静态检查。
63. 对新增 RED 测试及当前工作树执行 `git diff --check`，退出码 0、未发现空白/补丁格式错误；状态仅有计划中的未跟踪 `docs/` 和 `tests/test_paper_faithfulness.py`。因为测试文件尚未加入暂存区，普通 `git diff` 不显示其正文，这不影响后续按测试文件路径执行。
64. 用 `rg --files` 重新枚举实现范围，确认模型/损失核心分别为 `src/models/ov_orthkd.py`、`src/losses/ov_orthkd_loss.py`，现有测试共三个基线文件加新 RED 文件；配置与训练、预检、评估、导出、效率脚本均与实施计划中的路径一致，没有出现计划外重命名或缺失。
65. 完整重读当前模型、损失和新测试正文以准备最小实现：现有 `OVOrthKDStudent` 只有共享 `encoded_tokens` 且定位头直接消费共享维度；现有 `OVOrthKDLoss` 在损失对象里同时拥有学生/教师 projector、文本项把经温度缩放的余弦当 logits、正交项比较损失内部生成的学生强/弱投影，并无条件解引用若干可选教师工件。新测试的接口与设计一致，生产代码尚未修改。
66. 完整重读三个基线测试：原垂直切片测试用共享路径和旧 `OVOrthKDLoss(student_dim=...)` 接口；导出/预检测试通过 mock 教师构造两条样本并验证断点恢复；manifest 测试验证源清单无需教师工件。后续实现必须明确把旧垂直切片迁移到 `OVOrthKDLegacyLoss`/`legacy_shared`，同时保持其行为回归，而非让新 camera-ready 类暗中兼容旧公式。
67. 对任务 Python PID 23148 进行 10 秒 CIM 双快照：写入累计从 2,281,485,493 增到 2,285,704,373 字节，CPU 计数同步增长，命令行精确为本任务的官方 cu128 pip 安装。确认下载仍真实推进、没有挂起；继续保留该唯一进程。
68. 查询实施计划任务边界，确认八个任务起始行分别为 26、77、195、260、319、365、420、472；准备在等待大 wheel 期间严格按 Task 2/3 的测试清单继续补齐测试，不提前写生产实现。
69. 重读计划 Task 2/3 的逐步要求：Task 2 必须先观察缺少双路径接口的失败，再保留旧公式到独立 legacy 类并实现显式路径损失；Task 3 测试须覆盖必需弱特征缺失、宽松零回退、跨 CWD 相对路径、维度错误、独立生成器的确定性顺序，并保留 `weak_teacher_mask` 仅作兼容别名。后续测试按这些可观察行为编写。
70. 完整重读数据集与 loader 实现：当前所有资源路径直接相对进程 CWD 解析；缺工件是否回退仅受全局 `allow_missing_modalities` 控制；只有旧 `weak_teacher_mask`；DataLoader 未设置 `generator`/`worker_init_fn`，train shuffle 依赖全局 RNG。现有维度检查在成功加载后生效，但错误信息与记录身份未关联。这些是 Task 3 RED 的具体切入点。
71. 在原始任务书中交叉核验数据约束：`path_root` 必须统一解析 frame、spectrogram、teacher 数组、text 相对路径；`required_artifacts` 逐字段控制 fail-fast；正式配置至少要求 strong/weak feature 与 text；worker 使用 `torch.initial_seed()` 派生 NumPy/Python seed；三个 loader 都必须有固定且互不干扰的 generator。测试目标与原始要求一致。
72. 新增尚未执行的 `tests/test_strict_reproduction_data.py`：用独立手算/文件夹具覆盖必需弱教师特征缺失时同时报告字段和记录 ID、宽松模式零 canonical mask 与兼容别名、从不同 CWD 通过 `path_root` 读取图像/谱图/三类教师工件、教师维度错误、同 seed 重建 loader 且先迭代 val/test 不应改变 train 顺序。仍未修改生产代码。
73. 用本地官方 Python 3.11.9 仅对两个新增测试做语法编译，并运行 `git diff --check`；两者退出码均为 0。工作树可见变更仍只有未跟踪 `docs/` 与两个测试文件；语法编译产生的 `__pycache__` 被现有忽略规则排除。行为测试仍等待 5090 基线完成。
74. 再次只读检查远端安装：PID 23148 仍运行，累计写入已增至 2,528,228,533 字节（较上次约增加 242.5 MB），CPU 计数继续增长，已接近 2.56 GiB 主 torch wheel 的尾部。未启动重复安装。
75. 核对 `requirements.txt` 与计划 Task 4/5：torch/vision 明确要求另行按服务器 CUDA 安装，其余依赖受上界约束；训练阶段须一对一校验 implementation/path mode、禁止合成音频 logits、区分全局 optimizer-step 和单 epoch batch 上限、保存完整证据；评估阶段须导出非 pickle 的结构化预测并只用验证集校准一次阈值。后续测试会针对这些接口，而不会把 full-run 阻塞绕过。
76. 远端安装状态复查：PID 23148 写入累计增至 2,659,239,093 字节，CPU 继续增加，仍在运行；主 wheel 传输/落盘接近结束但尚未登记安装。继续等待同一进程，不采取重启或并行 pip。
77. 等待约 45 秒后复查，PID 23148 累计写入达到 2,749,781,173 字节，已非常接近官方 torch wheel 的 2,753,148,611 字节 Content-Length；进程仍正常推进。继续短时等待其完成安装事务。
78. 再等待约 30 秒后累计写入增至 2,916,734,133 字节，超过 wheel 下载长度且进程 CPU 继续增长，表明已进入缓存/解包安装阶段或继续处理小依赖，并非传输停滞。仍不干预该事务。
79. 继续等待约 45 秒，累计写入达到 3,033,572,533 字节，进程仍有 CPU/I/O 增量。安装事务处于持续解包/写入状态，未见失败退出或挂起迹象。
80. 下一次 45 秒观察得到累计写入 3,072,791,733 字节、CPU 继续增加；写入速率降低但不为零，任务进程仍处于运行态。保持单进程安装并转去准备后续 RED 测试。
81. 完整重读训练与 preflight：当前只有单一模型/损失构造；`set_seed` 未配置 deterministic；训练明确以强视觉 logits 加随机噪声伪造弱音频 logits；`max_train_steps` 实为每 epoch batch 上限；scheduler 固定 cosine；early-stop 不从 YAML 读取；只保存 best checkpoint；preflight 重复构造 scheduler/调用旧损失接口。Task 4 所列问题均能在当前代码中直接复现。
82. 再从任务书核验训练安全细节：唯一合法映射为 `camera_ready_explicit_paths→explicit_projected+OVOrthKDLoss` 和 `legacy_collaboration→legacy_shared+OVOrthKDLegacyLoss`；blocked full run 默认抛错，显式覆盖也必须写 `NON_CANONICAL_UNRESOLVED_RUN.txt`；正式 scheduler 保持 `UNRESOLVED`，smoke 才用 cosine；全局 `max_optimizer_steps` 与单 epoch `max_batches_per_epoch` 语义不得混淆。
83. 检索设计/计划中 Task 4 的已冻结接口，未发现比计划更具体的 `validate_repro_config` 输出目录参数；因此测试将把“校验”与“覆盖标记写入”作为一个可选 `output_dir` 行为固定下来，同时直接验证 cosine/step/UNRESOLVED scheduler、确定性开关和两种实现类映射。
84. 新增尚未执行的 `tests/test_training_reproducibility.py`：覆盖两种唯一实现映射、交叉/未知模式拒绝、blocked full-run 与覆盖标记、preflight 安全旁路、Python/NumPy/Torch seed 重复性、cuDNN deterministic 标志、cosine/step/UNRESOLVED scheduler、两种训练上限与旧 CLI 告警、YAML/CLI early-stop 优先级、真实弱 logits mask 要求以及校验不应修改输入配置。生产代码仍未改。
85. 对 Task 4 新测试执行本地 Python 语法编译并再次执行 `git diff --check`，均以退出码 0 通过；工作树新增测试列表与预期一致，没有生产代码变更或格式错误。
86. 远端状态复查：PID 23148 累计写入增至 3,158,787,253 字节，CPU 计数持续增加，安装仍健康推进。当前未出现退出错误或无增量重复样本，继续保持该进程并准备 Task 5 RED 测试。
87. 完整重读 `evaluate_pr_f1.py` 和任务书评价规范：现脚本虽已在 validation 选阈值再用于 test，但只收集扁平概率/标签，训练评价仍固定 0.5，均丢失样本/query/seen-unseen/segment 身份，也没有 total/seen/unseen 完整指标或 one-class AUROC 可用性标记。确定 Task 5 新接口围绕结构化 prediction dictionary、无 pickle NPZ、grouped metrics 和单次 validation calibration。
88. 新增尚未执行的 `tests/test_reproduction_evaluation.py`：用 echo-logit 假学生验证掩码展平后仍保留 ids、queries、split_types、sample offsets、segment indices；验证 Unicode NPZ 可在 `allow_pickle=False` 下读取；验证 total/seen/unseen 数量与单类 AUROC 显式不可用；构造验证/测试最优阈值不同的数组，要求最终 test 固定使用 validation 阈值且不存在 test calibration。生产代码仍未修改。
89. 对 Task 5 新测试执行本地语法编译与全工作树 `git diff --check`，退出码均为 0；未跟踪文件为设计/计划及四个 RED 测试文件，未出现生产代码变更。
90. 远端安装复查：PID 23148 累计写入增至 3,199,849,653 字节，CPU 继续增加但本段增量降至约 41 MB。为区分仍在网络传输与本地解包，下一步只读检查该 PID 的 TCP 连接和已出现的 site-packages 目录，不终止进程。
91. 只读诊断显示 PID 23148 同时保持三个 HTTPS Established 连接（目标端口 443），`site-packages` 尚无 torch 目录，而 `%TEMP%` 中存在本次 pip 创建的 metadata/unpack 目录；说明仍在 pip 下载/暂存阶段，尚未进入最终安装登记。网络连接有效，继续等待。
92. 进一步只读统计 pip unpack 目录发现关键异常：当前实际下载文件是 `torch-2.10.0+cu128...whl`（已 75,827,200 字节），同时残留 2.11.0 与 2.10.0 的 metadata。结合命令显式固定 `torch==2.11.0`，这表明未固定 torchvision/torchaudio 触发了解析器候选回溯，可能重复下载巨型 torch wheel；暂停“继续盲等”判断，先读取候选 metadata 的精确依赖约束再决定是否终止并改为兼容三件套。
93. 读取 metadata 得到 `torchvision 0.26.0+cu128` 精确要求 `torch==2.11.0`，与本任务请求兼容；torchaudio 候选也是 2.11.0。由于此前已发现同一远端用户下有与本任务无关的其他 pip 进程，2.10.0 临时文件不能安全归因给 PID 23148。暂不终止任何进程；下一步列出所有 Python/pip 命令行和 I/O，以避免误碰他人任务。
94. 当前全机 Python 进程清单只剩本任务的 venv wrapper PID 3964 与基础解释器子进程 PID 23148，二者命令行均是同一 `torch==2.11.0 torchvision torchaudio` 安装；子进程累计写入已达 3,259,630,773 字节。其他任务的 Python 已结束，但其临时目录可能仍残留；对 2.10 临时 wheel 做 10 秒大小快照，只有它继续增长才能归因于当前进程。
95. 10 秒快照确认 2.10 临时 wheel 始终为 75,827,200 字节且最后写入时间不变，而 PID 23148 总写入继续增至 3,278,288,053 字节；因此 2.10 文件是其他已结束任务的残留，不是本任务回溯下载。撤销异常假设，继续跟踪当前实际写入目标。
96. 扫描远端 `%TEMP%` 最近三分钟写入且大于 1 MiB 的文件未找到结果，说明 Win32 `WriteTransferCount` 不能直接等同于临时 wheel 文件长度（也可能包含 socket/管道 I/O），之前以其判断“下载字节”的表述应视为进程活动代理而非精确进度。下一步检查 pip HTTP cache 的近期文件和网络接收计数，继续以实际文件/包登记为完成标准。
97. pip HTTP cache 最近五分钟同样没有可枚举的 >1 MiB 新文件；PID 23148 的 `ReadTransferCount` 保持约 12.5 MB、`WriteTransferCount` 继续增至约 3.293 GB。由于进程仍有 HTTPS 连接和 CPU/I/O 增量但临时打开文件不可见，停止用字节计数估算剩余时间，仅以进程退出、`pip show` 和后续 CUDA import 作为权威完成证据。
98. 重读 Task 6 计划及现有 export/audit/efficiency/setup 代码：`export_manifest_records(limit=...)` 当前默认把未处理记录原样复制到输出，正是 smoke 泄漏风险；`check_manifest.py` 只有浅层缺失计数；尚无 strict reproduction audit、teacher identity 或 CUDA verifier；效率脚本用未同步的 `time.time()` 且写死 T=16；Linux setup 仅支持至 cu124。Task 6 文件范围与问题证据一致。
99. 读取任务书 strict audit 全部参数与 P0 清单：CLI 至少接收 train/val/test、path_root、stage、artifact scan、sample count、output JSON、expected segments、fail-on-warning；必须检查空/重复/跨 split ID、二值标签、路径/对齐/元数据、有限值与 exported 512/1/768/1024 维度，并报告 hash、T 直方图、`configured_max_segments=16`、`resampling_performed_by_dataset=false`。据此设计 valid T=10 与多故障 fixture。
100. 在现有 teacher export/preflight 测试中新增两个 RED：`limit=1` 默认输出必须物理截断为一条且 copied=0；只有显式 `copy_unprocessed_records=True` 才保留第二条并报告 copied=1。新增 `tests/test_reproduction_audit.py`：完整 exported T=10 fixture 验证计数/hash/seen-unseen/无重采样事实，多故障 fixture 同时验证重复、跨 split、非二值、缺路径、维度与 NaN P0 错误，另验证 expected T 不符仅在 `--fail-on-warning` 下转为非零。生产代码仍未改。
101. 对两个 Task 6 测试文件执行本地语法编译及 `git diff --check`，退出码 0；Git 仅提示已跟踪测试文件因本机 `core.autocrlf` 未来可能把 LF 转 CRLF，不是补丁错误。当前首次出现的已跟踪改动仅是该测试文件，所有生产文件仍未改。
102. 远端安装状态：PID 23148 累计 CPU 约 60.23 秒、活动 I/O 计数继续增长并保持三个 HTTPS Established 连接，进程未退出。按修正后的证据标准仅记录“仍活动”，不再用 I/O 数值推断下载百分比。
103. 重读 Task 7、当前两份主配置与 README：现有配置仍允许缺教师工件、没有 implementation mode/path mode、使用旧 `max_train_steps` 或未标 scheduler；README 仍把 paper-setting 配置作为可直接训练入口并只示例 cu124。Task 7 必须新增独立 blocked canonical 配置与 mock smoke 配置，并把文档明确改为 cu128、严格工件、六项归档阻塞和禁止真实 full run；旧 baseline 配置应保留而非覆盖。
104. 远端安装仍活动：PID 23148 CPU/I/O 均有小幅增量并保持三个 HTTPS 连接，尚未退出；不做百分比推断或干预。
105. 对 Task 2 RED 测试做变异思考后补充 `test_camera_ready_loss_backward_reaches_each_explicit_student_path`：同时开启 strong feature、weak feature、text 和 orth 项，反向后要求 decision/audio_aux/query 三条显式学生路径均获得有限梯度，避免仅比较前向数值却漏掉路径断连。生产代码仍未修改。
106. 补充后的 Task 2 测试通过本地语法编译，`git diff --check` 仍退出 0；仅重复出现已记录的 autocrlf 提示。
107. 再等待约 45 秒后，远端 PID 23148 的 CPU 与活动 I/O 均继续增长，三个 HTTPS 连接仍建立，进程尚未完成；继续保持单一安装事务。
108. 又一轮约 45 秒观察仍为同一状态：进程 CPU/I/O 有增量、三个 HTTPS 连接保持、尚未退出。为判断除主 wheel 外是否还有大型依赖，下一步只读查看已下载的 torch 2.11 metadata 全部 `Requires-Dist`，不改变安装。
109. torch 2.11 Windows metadata 的必需依赖仅为 filelock、typing-extensions、setuptools<82、sympy、networkx、jinja2、fsspec，均无另一大型 CUDA wheel；opt-einsum/optree/pyyaml 是 extras。故长耗时仍应归于 2.75 GB 主 wheel 的受限传输/暂存，而非隐含多 GiB 依赖集合。
110. 再等待约 50 秒，PID 23148 仍有 CPU/I/O 增量并维持三个 HTTPS 连接，未完成。为评估更快且可校验的备选路径，在不干预远端进程的前提下对同一 PyTorch CDN wheel 做本地小范围测速；只有本地吞吐显著更高才考虑完整下载+SHA 校验+SCP，否则继续远端原进程。
111. 本地对同一 torch 2.11.0+cu128 wheel 成功做 20 MiB HTTP Range 测速：20,971,520 字节耗时 51.97 秒，约 0.385 MiB/s。按此速度完整下载还需约两小时，外加 SCP，明显不优于已持续推进的远端下载；因此不启动本地完整下载，也不终止远端进程。测速文件位于本机任务临时目录、不属于项目产物。
112. 尝试按绝对路径与根目录校验后删除该 20 MiB 临时测速文件，但本地工具策略在命令执行前拒绝了删除命令；没有文件被删除或改变。该文件继续留在 `C:\Users\lwz20\AppData\Local\Temp\OVOrthKD-R0`，不进入仓库或最终上传内容。
113. 本地测速期间远端任务 PID 23148 仍持续活动，CPU/I/O 增幅明显且三个 HTTPS 连接保持，验证远端实际吞吐高于本地 0.385 MiB/s 备选；继续等待远端原事务。
114. 用显式 UTF-8 读取 `all.md` 尾部核验日志完整性：第 96–113 条中文、路径、数值和 Markdown 均正常显示；此前终端乱码仅因首次 `Get-Content` 未指定编码，文件本身未损坏。
115. 远端任务 PID 23148 继续保持三个 HTTPS 连接及 CPU/I/O 增量，尚未完成；无错误输出或包登记证据，继续等待。
116. 再等待约 50 秒仍未退出，CPU/I/O 活动与三个 HTTPS 连接持续。为找到此前普通枚举未显示的打开临时文件，下一步用 `-Force` 枚举 pip-unpack 下所有文件（含隐藏项）并按长度排序；该检查只读。
117. `-Force` 枚举仍只看到已静止的 75.8 MB torch 2.10 残留及两批 metadata，没有可见的当前 2.11 主 wheel 临时文件；说明 pip/Windows 正使用不可枚举的打开临时对象或 delete-on-close 文件。没有发现磁盘上可安全接管/校验的完整 wheel，继续等待原进程退出。
118. 核对远端时钟与进程创建时间：安装自 21:00:54 运行至 22:00:38，约一小时。结合 2.75 GB wheel、本地仅 0.385 MiB/s 的测速及远端持续连接，这一时长虽很长但仍符合受限大文件传输量级；尚不足以在仍有活动时判为挂起。
119. 继续等待约 50 秒，安装进程仍在运行且本轮 CPU 增长较此前明显、网络连接不变，可能接近校验/处理阶段，但没有包登记证据前不宣称完成。
120. 下一轮约 50 秒观察仍有 CPU/I/O 增量及三个 HTTPS 连接，未退出。为不再纯等待，准备只读检查此前观察到的远端现有 `smc_gate1_env` 是否已具备 torch/timm/pytest；若完整，仅作为同一 5090 主机上的临时基线/RED 执行器，不修改该环境，最终 CUDA 与完整验证仍必须在本任务隔离 venv 重跑。
121. 远端用户目录只读枚举确认现有环境路径为 `C:\Users\LXT\smc_gate1_env`，另有其工作目录；尚未执行其中程序或修改任何内容。下一步仅调用该环境 Python 输出版本与模块可用性。
122. 现有环境 Python 可运行，版本为 3.11.16；首次用 `python -c` 输出模块字典时，PowerShell 到原生程序的内层双引号被剥离，导致模块名变成未定义标识、退出码 1。该失败未导入或修改任何包；改用无需嵌套引号的 `pip show` 查询。
123. `smc_gate1_env` 的 `pip show` 明确报告 torch、torchvision、timm、pytest、PyYAML、scikit-learn 均未安装，退出码 1；该环境不能用于本仓库基线/RED，且未被修改。放弃临时复用方案，继续等待本任务 venv。
124. 本任务 PID 23148 复查仍为运行态，CPU/I/O 继续增长且三个 HTTPS 连接保持；未登记完成。
125. 再等待约 50 秒，PID 23148 仍运行并有较小 CPU/I/O 增量，三个 HTTPS 连接不变；远端下载未完成。为避免开发完全被大文件带宽串行阻塞，下一步只读核对本机现有 Anaconda 是否已具备完整测试依赖；若可用，可先在本地观察基线与 RED，但最终全套/CUDA 仍必须在 5090 隔离 venv 重跑。
126. 首次本机 Anaconda 查询使用假定路径 `C:\ProgramData\anaconda3\python.exe`，该路径不存在，命令在启动 Python 前退出码 1；没有环境或文件变化。改为从 `Get-Command`/`where.exe` 发现实际解释器路径，而不继续猜测。
127. 解释器发现结果：本机 Anaconda 实际位于 `C:\Users\lwz20\anaconda3\python.exe`，另有官方 Python 3.11.9；Conda 命令也来自该用户目录。下一步仅查询 Anaconda 已装包。
128. 本机 Anaconda 已有 torch 2.10.0+cpu、torchvision 0.25.0、pytest 8.4.2、PyYAML 6.0.3、scikit-learn 1.7.2、Pillow 12.2.0、NumPy 2.3.5，但缺 `timm`；因此尚不能导入学生模型。继续查询本机官方 Python 3.11 的已有第三方包，仍不安装或修改环境。
129. 本机官方 Python 3.11 有 PyYAML/scikit-learn/Pillow/NumPy，但缺 torch、torchvision、timm、pytest，不能替代。为满足 TDD 且不污染任何现有环境，决定把仅缺的纯 Python `timm` 无依赖安装到任务临时目录，通过 `PYTHONPATH` 叠加到已有 Anaconda CPU torch 做本地“预备基线/RED”；该临时 harness 不作为 5090 或最终验证证据。
130. 将 `timm 1.0.28` 以 `--no-deps --target` 安装到本机任务临时目录，使用 pip 缓存的 2.6 MB wheel，退出码 0；未修改 Anaconda site-packages、项目或远端。该版本满足仓库 `>=1.0.15,<1.1` 约束。
131. 用本地临时 CPU harness 只运行三个原始基线测试函数（排除新增 RED）：`test_check_manifest.py`、原垂直切片、原 export/preflight。结果 `3 passed in 8.28s`，pytest 退出码 0，说明未修改生产代码的本地基线健康。该结果是预备证据；5090 隔离环境就绪后仍会重跑同一基线。
132. 在同一本地 harness 首次执行 Task 2 focused RED：`tests/test_paper_faithfulness.py` 得到预期的 `17 failed in 3.39s`、退出码 1。失败根因集中且正确：student 不接受 `projection_dim/path_mode`、缺 paper text helper、旧 loss 仍要求 `student_dim`；没有环境型或测试夹具型异常。已满足先观察真实失败再写生产实现的 TDD 门槛。
133. 在写实现前再次逐行对照任务书推荐核心代码：确认 camera-ready loss 在 `alpha_orth>0` 时也必须要求两类教师 feature 与 mask、strong feature 暂保维度 mean 并标记归档阻塞、paper text 为 `(cos+1)/2` probability BCE、legacy temperature-logit 分支仅受控使用、stats 可暂时同步为 Python float。另确认两个包 `__init__.py` 当前只导出旧单类，需显式加入 `ProjectionHead` 与 `OVOrthKDLegacyLoss`。
134. 首次生产实现改动：把 `ProjectionHead` 移入模型模块并导出；`OVOrthKDStudent` 新增经校验的 `explicit_projected|legacy_shared` 模式和 `projection_dim`。显式模式创建 decision/audio_aux/query 三个 projector，定位头只读 decision；legacy 模式不创建这些参数且头保持 shared 维度。forward 新增四类路径输出和 `gate_logits`，`segment_features` 继续兼容指向 shared。尚未改损失。
135. 立即运行 Task 2 三个模型 focused 测试，结果 `3 passed in 10.07s`、退出码 0：显式定位头输入、legacy 无 projector/shared head、非法 mode 拒绝均转绿。
136. 首次尝试在一个 `apply_patch` 中同时“删除并重新添加”同一路径的 loss 文件，补丁校验器因同一路径多操作而在应用前拒绝；该调用没有写入 legacy 文件、camera-ready loss 或 losses 导出。改为分别新增 legacy、单次 Update 重写现有 loss、再更新导出。
137. 完成 Task 2 损失拆分：新增 `OVOrthKDLegacyLoss`，保留基线所有 student projector、temperature-logit text BCE、参数名与公式；camera-ready `OVOrthKDLoss` 改为只拥有三类教师 projector，按 alpha 条件严格要求工件/mask，使用映射余弦 probability BCE、显式 decision/audio/query 输入和 `cos²` 正交项；`_masked_mean` 校验形状；losses 包同时导出两类。旧 loss 文件通过一次可恢复的 delete/add 原子序列替换成功。
138. 运行完整 Task 2 paper-faithfulness 测试，结果 `17 passed in 3.47s`、退出码 0；此前 17 个 RED 全部转绿，包括三条显式路径有限梯度。下一步把原垂直切片明确迁移到 `legacy_shared + OVOrthKDLegacyLoss`，验证旧行为没有被新默认模式暗中改变。
139. 修改原垂直切片测试的声明而非公式：student 显式指定 `path_mode="legacy_shared"`，loss 导入/构造改为 `OVOrthKDLegacyLoss`；其原有输入、权重默认、shared feature 形状、backward 与 evaluate 断言保持不变。
140. 联合运行 legacy 垂直切片与全部 paper-faithfulness 测试，结果 `18 passed in 17.65s`、退出码 0；证明双路径/camera loss 新行为与冻结 legacy 行为同时通过本地预备验证。
141. 首次执行 Task 3 strict-data RED，结果 `5 failed in 6.30s`、退出码 1。四个失败明确来自 dataset 不接受 `path_root`，第五个显示同 seed 重建且先迭代 val/test 后 train 顺序不同；正好捕获路径/strict artifact/canonical mask 与独立 generator 缺口，没有夹具异常。开始最小数据层实现。
142. 首次数据层补丁因同一 patch 文本对 `ov_avel_dataset.py` 使用了两个独立 Update 操作，被校验器在应用前拒绝；数据代码没有发生部分修改。将 `seed_worker` hunk 合并进该文件的单一 Update 操作后重试。
143. 完成 Task 3 最小数据实现：dataset 先以 `path_root` 解析 manifest 和所有图像/谱图/教师/text/override 路径；`required_artifacts` 对缺工件按字段与记录 ID fail-fast，宽松模式仍可置零；维度错误补充字段/记录上下文；新增 canonical `weak_teacher_feature_mask` 并保留相同的旧别名。新增/导出 `seed_worker`，train/val/test 使用 seed、seed+1、seed+2 的独立 generator。
144. 运行 Task 3 focused 测试，结果 `5 passed in 4.20s`、退出码 0；此前路径、strict 缺失、canonical mask、维度错误和独立顺序五个 RED 全部转绿。
145. 联合回归 Task 2、Task 3 与 legacy 垂直切片，结果 `23 passed in 5.63s`、退出码 0；模型/损失与数据改动目前无交叉回归。
146. 首次执行 Task 4 training-reproducibility RED，在收集阶段因 `scripts.train_ov_orthkd` 尚无 `build_scheduler` 而退出码 2；这是预期的接口缺失，不是环境/测试错误。开始实现配置校验、唯一映射、deterministic seed、scheduler、limits、early-stop 与真实 weak-logit guard，再进入训练循环证据改造。
147. 在训练模块新增第一批 Task 4 核心接口：CLI 增加 blocked override 与明确 step/batch 参数；`set_seed` 配置 deterministic algorithms/cuDNN；`validate_repro_config` 默认拦截 full run 并在显式覆盖时写 NON-CANONICAL 标记；scheduler 支持 cosine/step 并拒绝 UNRESOLVED；新增训练上限、early-stop、weak-logit guard、SHA256 helper；builder 实施两种 mode/path/loss 唯一映射，旧无 reproduction 配置默认落到 legacy 以保持兼容。
148. 运行 Task 4 配置/安全 focused 测试，结果 `15 passed in 5.29s`、退出码 0；两种 mapping、blocked marker、preflight 旁路、deterministic seed、scheduler、limits、early-stop、禁止伪造 weak logits 均转绿。继续把这些 helper 接入实际 train/preflight 路径及运行证据保存，不能只停留在可测试孤立函数。
149. 新增生产 `compute_loss_for_batch`，根据 loss 实例只允许 legacy shared 或 camera explicit 参数集，统一使用 canonical weak feature/logit masks 并在任何 weak-logit KD 前调用真实工件 guard；同时修正 legacy 无显式 loss 权重配置时继续采用基线 0.8/0.25/0.3/0.15 默认，而 camera 使用论文式 0/0.1/0.8/0.5 默认。
150. preflight 已接入 `validate_repro_config(preflight=True)`、deterministic seed、生产 builder、生产 loss dispatch 和可配置 scheduler；checkpoint 增加 implementation mode/global step，summary 增加 mock/mode 标签，resume 使用相同 scheduler builder。下一步运行原 mock export/preflight 回归，确认接线无误。
151. 运行原 mock export/preflight 与 Task 4 测试联合回归，结果 `16 passed in 5.68s`、退出码 0。随后把 helper 全面接入 `main`：blocked 校验发生在数据加载前；写 runtime/resolved config、git state、pip freeze、manifest hashes；使用可配置 scheduler；删除整个随机 weak-logit 代理分支；按全局/per-epoch 两种限制维护 `global_step`；每 epoch 写 history、last，按 val AP 写 best，checkpoint 含 mode/global_step/optimizer/scheduler/scaler/config；最终重新加载 best 再评价并写 final metrics。
152. 对更新后的 train/preflight 做本地 Python 语法编译，退出码 0；源码检索只剩真实 guard 的报错文本 `Synthetic logits are forbidden`，不存在 `jittered`、`weak audio proxy` 或 `randn_like(weak_teacher_logits)` 生成路径；`git diff --check` 退出码 0，仅有已知 autocrlf 提示。
153. 再次联合运行 Task 4 全部 15 项测试与原 mock preflight，结果 `16 passed in 5.61s`、退出码 0；实际 preflight forward/backward/evaluate/save/resume 接线保持健康。
154. 5090 安装进程仍运行并保持三个 HTTPS 连接，开发期间 CPU/I/O 累计继续显著增长，尚无包登记；继续并行本地 TDD，最终远端复验门槛不变。
155. 首次执行 Task 5 evaluation RED，在收集阶段因 `evaluate_pr_f1.py` 尚无 `evaluate_prediction_sets` 退出码 2；正是结构化评估接口缺失。开始在生产评价路径实现逐样本 offsets/身份、Unicode NPZ、total/seen/unseen 指标、one-class AUROC 状态和 validation-only threshold calibration。
156. 在训练/评价模块实现 Task 5 核心：`collect_predictions` 按 mask 保留 sample id、query、从显式字段/meta/domain 解析的 split type、sample offsets 与原 segment index；`save_predictions_npz` 固定八个字段并用 Unicode 数组；`compute_grouped_metrics` 对 total/seen/unseen 报 threshold、accuracy/F1/AP/AUROC 可用性、正例率与样本/段数；`evaluate_prediction_sets` 只在 validation 求一次 PR 最优阈值并冻结应用到两组指标，完整保存 validation PR 数组。checkpoint student 构造也复用唯一 mapping builder。
157. 将结构化评价接入训练与独立评估：每次 best 保存 validation predictions；训练结束重载 best 后保存 validation/test NPZ、validation PR curve 和冻结阈值下的 grouped final metrics；`evaluate_pr_f1.py` 改为收集/保存结构化预测、以 validation calibration 生成曲线/摘要，并保留 test PR 仅作曲线而不选 test 阈值。grouped metrics 同时补充 precision/recall，旧 CSV 列不再被错误地用正例率代替。
158. 联合运行 Task 5、Task 4 与 legacy pipeline，结果 `19 passed in 5.55s`、退出码 0；结构化 round-trip、grouped one-class 行为、validation-only 阈值和训练安全均保持通过。
159. 首次执行 Task 6 export/audit RED，在收集阶段因 `scripts.audit_mm26_reproduction` 不存在而退出码 2；符合预期工具缺失。开始先修 export limit 默认物理截断，再实现 strict audit 及其他运行工具。
160. 修复 teacher export：pipeline/file API 新增 `copy_unprocessed_records=False`，`limit` 默认只写已处理记录；CLI 增加显式 `--copy-unprocessed-records`，summary 的 copied 计数只统计真正复制项。
161. 新增 `scripts/audit_mm26_reproduction.py`：实现任务书全部 CLI 参数、JSONL/JSON/hash、split 内重复与跨 split 重叠、ID/二值 label/T/路径对齐/元数据检查、source/exported 分阶段、none/sample/full 工件扫描、512/1/768/1024 维度与 NaN/Inf、canonical count 对照、T/frame/label/category 直方图、path/artifact 分组错误、固定 capacity=16 且不重采样事实，以及 P0/可选 warning 退出码。
162. 运行 Task 6 audit 与 teacher export/preflight 测试，结果 `6 passed in 5.52s`、退出码 0；默认截断、显式复制、valid T=10、六类 P0 故障和 fail-on-warning 均通过。
163. 新增运行工具：`scripts/verify_cuda_runtime.py` 强制 CUDA 可用并用同步 CUDA events 执行 fp16 方阵乘法、记录 Python/PyTorch/CUDA/cuDNN/GPU/显存/数值有限性；`scripts/setup_server.sh` 修正为稳定版 cu128 安装；重建 `scripts/measure_efficiency.py`，按真实张量规格和精确 T 标签用 CUDA events（CPU 回退为 perf_counter）测量学生延迟。上述工具尚待 5090 环境完成后执行。
164. 为实现教师身份审计，首次组合读取三个真实教师 wrapper 文件时工具输出超过上限而截断，不能把该次截断内容作为完整 API 证据；随后改用定向 `rg` 检索，确认入口分别为 `InternVideo2ClipB14Teacher`、`BEATsAudioTeacher`、`ClapTextTeacher`，并定位三类 checkpoint、InternVideo2 `num_frames`、BEATs `finetuned_model`、CLAP `version` 以及各自 export/encode 方法。下一步分块读取精确实现。
165. 首次分块读取命令成功取得 InternVideo2 wrapper 的关键区段：真实上游类为 `multi_modality.models.internvideo2_clip_small.InternVideo2_CLIP_small`，配置 `model_cls=InternVideo2_CLIP_small`、默认 `num_frames=8`、`align_dim=512`，并显式接收 vision/text/extra 三个 checkpoint；其 segment export 输出 float32 visual features 与余弦温度 logits。随后 PowerShell 对单元素 range 的类型处理报 `Argument types do not match`，导致 BEATs/CLAP 未读；该命令退出码 1，未修改文件，下一步改为逐文件读取。
166. 逐文件完整读取 BEATs/CLAP wrapper 成功：BEATs 从显式 repo 导入官方 `BEATs`/`BEATsConfig`，checkpoint 顶层必须含 `cfg`/`model`，强制 `finetuned_model=False`，默认/配置特征维度 768，并对 token 做 mask-aware mean pooling；CLAP 从显式 repo 导入 `msclap.CLAP`，以显式 checkpoint、默认 `version=2023` 构造，特征维度取 `model.args.d_proj`（默认 1024），可选归一化但 wrapper 默认不归一化。该读取退出码 0，未修改生产文件。
167. 定向检索任务书与既有配置，确认 `inspect_teacher_identity.py` 必须打印并保存 wrapper/upstream 类、上游仓库 Git SHA、checkpoint 绝对路径/SHA256/顶层 keys、feature dimension、num_frames、CLAP version、BEATs finetuned_model 与单样本 shape/finite/norm；同时确认现有配置使用三组明确 repo/checkpoint 路径。检索命令还误包含不存在的 `scripts/export_mm26_teacher_targets.py`，因此在已取得所需结果后整体退出码为 1；未修改文件，后续使用真实 `scripts/export_teacher_artifacts.py` 路径。
168. 为教师身份工具新增三项 TDD 契约测试：完整静态 provenance、Base/B14 声明与 Small 实际类冲突阻断、BEATs finetuned checkpoint 阻断。首次 focused RED 在测试收集阶段因 `scripts.inspect_teacher_identity` 尚不存在而失败，退出码 1；这是预期的真实接口缺失，开始编写最小生产实现。
169. 新增 `scripts/inspect_teacher_identity.py` 初版：只解析显式路径、流式 SHA256、Git SHA、checkpoint keys/schema、声明冲突与 finetuned 标志，并预留真实单记录 smoke/JSON 输出。首次转绿运行在导入阶段因本地临时 harness 没有 `librosa` 而失败；根因是静态审计模块顶层导入了仅 smoke 才需要的真实 BEATs wrapper，导致静态功能不必要地依赖音频栈。按系统化调试改为 smoke 内惰性导入，而不是给临时环境追加无关包。
170. 把三个真实 teacher wrapper 改为仅 `_run_smoke` 内惰性导入后，教师身份 focused 测试 `3 passed in 5.65s`、退出码 0；静态 provenance、InternVideo2 类冲突和 finetuned BEATs 三项契约均转绿。
171. 再次只读检查 5090 环境安装：本任务 wrapper PID 3964 与实际 pip PID 23148 仍自 21:00:54 持续运行，后者累计 CPU 已增至 110.39 秒；venv 内 torch/torchvision/torchaudio 仍未登记完成。保持该唯一下载进程，不重复启动、不终止。
172. 对 Task 6 工具执行语法编译与 `--help` 冒烟：全部文件 py_compile 成功，audit/CUDA/identity 的 help 成功，但 efficiency help 退出码 1。隔离复现得到根因：直接运行 `scripts/measure_efficiency.py` 时未把仓库根加入 `sys.path`，因而找不到 `src`；另复核发现 `setup_server.sh` 虽已支持 cu128，默认说明和值仍为 cu124。开始做两项局部修复。
173. 修复 efficiency 的仓库根导入，并把 `setup_server.sh` 的默认 PyTorch 通道及帮助文字统一为 cu128。重新执行八个关键 Python 文件编译、四个工具 `--help`、setup Bash 语法与 Task 6 联合测试，全部退出码 0；联合结果 `9 passed in 8.24s`。教师身份、审计、export limit 与运行工具的本地实现阶段完成，实际 CUDA/真实 teacher 结果仍分别等待 5090 环境与确切 checkpoint 身份。
174. 为两套新配置增加 TDD 契约测试，覆盖 canonical 的六项阻断事实/严格工件/显式路径/UNRESOLVED scheduler，以及 smoke 的 mock-only/小 batch/无增强/两批上限/cosine。首次 RED 得到 `2 failed in 0.13s`、退出码 1，两个失败都精确来自目标 YAML 文件尚不存在；开始按任务书冻结配置。
175. 新增 `configs/ov_orthkd_mm26_repro.yaml` 与 `configs/ov_orthkd_mm26_smoke.yaml`。canonical 配置逐字冻结六项 `blocked_archival_facts`、严格三类工件、显式 projected 路径、论文权重、无限制正式预算和 `UNRESOLVED` scheduler；真实 teacher repo/checkpoint 仅使用 `UNRESOLVED/...` 占位，避免误认近似文件。smoke 配置显式 `mock_only: true`，三种 teacher backend 均为 mock，限制 2 epoch/每 epoch 2 batch，且产物标签不可冒充真实复现。配置 focused 测试 `2 passed in 0.04s`、退出码 0。
176. 为满足“没有本地 smoke manifest 时由 mock pipeline 自动生成”的要求，新增 fixture builder 行为测试：期望在给定根目录生成 train/val/test 各 4 条记录、真实可读图像/谱图占位、seen/unseen 标签与四类 mock teacher 工件。首次 RED 在收集阶段因 `scripts.create_mm26_smoke_fixture` 尚不存在而退出码 1，开始实现有硬上限的确定性生成器。
177. 新增 `scripts/create_mm26_smoke_fixture.py`：固定 split seed、最多 32 条/每条最多 16 段，生成可读 RGB frame/谱图、短 waveform `.npy`、seen/unseen 元数据与 512/768/1024 维 mock teacher 工件；所有记录显式标记 `mock_only_r0`，不会下载数据。配置/fixture 联合测试 `3 passed in 3.64s`、退出码 0。
178. 更新根 `README.md`：环境入口改为官方 cu128，加入严格 mock fixture/preflight、source/export audit、教师身份审计命令；明确 camera-ready 与 legacy 的一对一 mapping、checkpoint/report 标签、validation-only 阈值；同时写明 canonical 配置会在数据加载前被六项事实阻断，`--allow-blocked-reproduction` 仅产生 NON-CANONICAL 诊断，不可报告为论文结果。
179. 在本地临时 CPU harness 执行 `python -m compileall -q src scripts tests` 与完整 `pytest -q`，两条命令均退出码 0；完整测试结果为 `55 passed in 11.16s`。这是代码级预备回归，最终环境证据仍以 5090 干净 venv 的重复执行为准。
180. 执行仓库原有 `python scripts/smoke_test.py`，退出码 0，输出 `OV-OrthKD smoke test passed.`；legacy 垂直切片仍保持可运行。
181. 尝试对 5090 pip PID 做含 TCP pipeline 的五秒双快照时，SSH 远端的 Windows `cmd` 在进入 PowerShell 前错误解析了管道，把 `Select-Object` 当作外部命令，退出码 1；没有执行写操作，也未改变安装进程。后续改用 UTF-16LE Base64 编码的 PowerShell `-EncodedCommand` 消除多层 shell 解析歧义。
182. 使用 `-EncodedCommand` 成功取得 5090 双快照：PID 23148 存活，五秒内 CPU 从 117.828 增至 117.891，工作集/私有内存稳定，并保持三个到官方/CDN 地址的 HTTPS Established 连接；pip show 仍提示 torch 未完成，因此组合命令随 pip show 返回退出码 1。进程尚有网络活动但推进很慢，继续保留；下一步只读定位 pip 临时 wheel 的实际文件大小与时间戳以判断是否仍增长。
183. 只读检查 5090 pip 的 CIM 传输计数与用户临时目录：PID 23148 命令行仍是唯一的 `torch==2.11.0 torchvision torchaudio` cu128 安装，累计 `WriteTransferCount=4,933,829,813` 字节，明显高于早期快照，说明一直有实质下载/缓存写入；临时目录可见的 75.8 MB torch 2.10 文件时间戳较早，确认不是本任务当前 2.11 下载目标。继续等待当前进程，不碰旧残留。
184. 在本地生成严格 mock fixture 并按任务书参数运行 camera-ready preflight（CPU 预备验证）：train/val/test 各导出 4/4 条，全部 frame/谱图/audio/strong feature+logit/weak feature/text 工件零缺失；preflight 退出码 0，`mock_only=true`、`implementation_mode=camera_ready_explicit_paths`，一批 forward/backward 总损失 1.571087，各分项有限，val/test 指标成功计算，checkpoint resume 恢复 epoch 1 与 best AP 0.709524。该结果明确是 mock-only CPU 预备证据；5090 CUDA 将重复同一命令。
185. 直接运行 canonical 训练入口验证安全闸：命令在任何 manifest/模型加载前按预期抛出 `Paper reproduction full run is blocked by unresolved archival facts`，退出码 1；未启动训练。复核教师身份报告字段后，决定在 canonical teacher 配置中额外显式保存论文/历史声明的 Base/B14 类名，使审计能同时展示“声明类”与 wrapper 实际 Small 类，而不只依赖自由文本 teacher name。
186. 在 canonical config 新增 `teacher_export.internvideo2.declared_model_class: InternVideo2-Base / CLIP-B14`，identity 报告新增该字段并用它和固定上游 `InternVideo2_CLIP_small` 对照；教师身份与配置联合回归 `6 passed in 5.80s`、退出码 0。
187. 对 canonical 配置运行教师静态身份审计并保存 `reports/teacher_identity_static.json`。脚本按设计退出码 1、状态 `blocked`：精确记录 wrapper/upstream/维度/num_frames/CLAP 版本；确认五个 checkpoint、三个上游 repo 均为明确的 UNRESOLVED 缺失项；另独立报告 Base/B14 声明与 `InternVideo2_CLIP_small` 的类冲突，并标记未运行 smoke 不足以批准 export。没有下载或猜测任何 teacher 资源。
188. 对本地生成的 mock-only 三 split 运行 exported/full artifact audit 并保存 `reports/mm26_smoke_artifact_audit.json`，退出码 0：12 条记录、4 类、seen/unseen 各 2 类、24 段正负各 12、T=2、无重复 ID、无跨 split 重叠、无路径/工件/NaN/Inf/维度错误，三份 manifest SHA256 已记录；canonical split 数故意不匹配且报告明确显示，因为该数据仅为 bounded smoke。
189. 执行工作树静态盘点：当前修改覆盖 README、train/evaluate/preflight/export/setup/efficiency、模型/损失/数据/teacher pipeline 与既有测试，新增两套配置、设计/计划、三类审计工具、mock fixture 和六组专项测试；已跟踪 diff 为 1376 insertions/317 deletions（尚不含 untracked 新文件）。`git diff --check` 未报告 whitespace error；末尾禁用模式 `rg` 没有找到 TODO/FIXME/伪造弱 logits 等目标，因此组合命令仅因 `rg` 的“无匹配”语义退出码 1，而非检查失败。
190. 首次运行完整 camera-ready mock 训练入口时，epoch 1 已完成 2 个 optimizer steps 并计算 val AP 0.667857，但保存首个 best checkpoint 的结构化预测时抛出 `UnboundLocalError: val_predictions`，退出码 1。根因已定位：训练循环仍调用旧 `evaluate()` 只返回 metrics，而新增 `val_predictions` 仅在 eval-only 分支赋值；需要把“收集预测+生成 grouped metrics”合并为单一生产 helper 并让两个入口复用。
191. 为该接线缺陷新增 helper 契约测试；focused RED 按预期因 `evaluate_with_predictions` 不存在而失败，退出码 1。该测试将锁定“保存 best 所用 predictions 与计算 selection metrics 的 predictions 必须来自同一次收集”。
192. 实现 `evaluate_with_predictions`，让 eval-only validation 与每个训练 epoch 均从同一次结构化收集获得 predictions 和 total metrics；focused 测试 `1 passed in 4.36s`、退出码 0。开始从头重跑完整 mock 训练以验证 best/last/final 端到端路径。
193. 重跑完整 mock 训练已退出码 0：2 epoch、4 个 global optimizer steps、best/last/history/结构化 NPZ/final metrics 全部写出，validation 阈值仅校准一次后冻结用于 test。该运行同时暴露次级证据缺口：尽管源 manifest 有 seen/unseen，最终 grouped 两组 sample_count 都为 0；根因是 dataset/collate 未把顶层 `split_type` 传到 batch，collect 只能退回 unknown domain。开始为元数据传递补回归测试并修复。
194. 新增 dataset→collate seen/unseen 传递测试；focused RED 得到预期 `KeyError: split_type`、退出码 1，确认缺口确实位于数据返回契约而非评估分组算法。
195. dataset 现在从顶层或 meta 的 `split_type/seen_unseen/novelty` 解析并返回规范化字符串，collate 同步保留该字段；严格数据、结构化评估与训练复现联合回归 `25 passed in 11.04s`、退出码 0。开始再次跑完整 mock 训练，确认最终 seen/unseen 不再为空。
196. 第三次完整 mock 训练退出码 0，耗时 47.5 秒：global_step=4，best epoch 2/val AP 0.684524；validation 校准阈值 0.248287 后冻结应用于 test。最终 total/seen/unseen 均有非零样本：validation 每个子组 2 samples/4 segments，test 同样各 2/4，证明 split_type 数据链已修复；best/last/history、预测 NPZ、PR 曲线与 final metrics 全路径完成。
197. 5090 安装状态发生变化：实际 pip PID 23148 已结束，但 venv 内 torch/torchvision/torchaudio 均未登记，状态检查因此退出码 1；说明长时间下载最终失败而非完成。未直接重启安装；按系统化调试先检查父/wrapper 状态、退出日志、pip cache 与最新临时文件，确定失败点和可复用字节后再选择恢复路径。
198. 安装失败诊断：wrapper PID 3964 也已结束，未留下重定向日志；pip cache 目录存在但 `pip cache list torch` 显示无已缓存 wheel，本次 2.11 临时文件已被 pip 清理，仅余更早的 75.8 MB torch 2.10 残片与 dependency metadata。结合累计写入约 4.93 GB 而目标 wheel 约 2.75 GB，最符合“慢链路中途失败后 pip 从头重试、最终耗尽 retries”的模式。下一步先查 5090 是否已有可复用官方 CUDA torch；若无，则改用落盘且支持 Range 续传的官方 wheel 下载并保留日志，避免 pip 临时文件再次丢失。
199. 只读扫描发现 5090 的另一现有环境 `C:\Users\LXT\smc_gate1_env` 已在本任务运行期间完成一套 CUDA torch（`torch_cuda.dll` 约 908 MB），而系统 PATH 仍只有 WindowsApps shim；E: 其他目录未递归扫描，避免干扰大盘。该环境属于其他工作，不安装、不修改；下一步只读核验其 Python/PyTorch/CUDA/来源与包清单，若是兼容的官方 cu128，可仅把所需已安装分发文件复制到本任务隔离 venv，避免再次公网下载和污染原环境。
200. 只读核验其他环境：已安装的是官方元数据标识的 `torch 2.10.0+cu128`，位置明确，依赖列表为 filelock/fsspec/jinja2/networkx/sympy/typing-extensions，`pip check` 无断裂；该环境没有 torchvision/torchaudio，因此组合 import 首先因 torchvision 缺失而退出码非零，尚未取得 GPU capability。下一步单独导入 torch 验证 sm_120，再盘点 torch 分发顶层文件；原环境仍不做任何变更。
201. 单独导入核验成功：源环境 Python 3.11.16 的 `torch 2.10.0+cu128` 使用 CUDA 12.8、cuDNN 91002，`torch.cuda.is_available=True`，识别 RTX 5090 且 capability `[12,0]`。torch 分发顶层严格为 `torch`（约 4.536 GB）、`torchgen`、`functorch` 与对应 dist-info；本任务 Python 3.11.9 ABI 兼容。决定只读复制这四个明确分发目录到本任务隔离 venv，再在本任务环境独立安装其余依赖/torchvision/torchaudio并执行 pip check；不改动源环境。
202. 首次用隐藏 `Start-Process` 启动四目录复制时返回 PID 26756，但该进程立即结束、目标目录和状态文件均未产生，stdout/stderr 日志也均为 0 字节；说明 Base64 内层命令未实际执行。没有发生部分复制或源环境变化。改为在单一远端 PowerShell 中使用 `robocopy /E /MT` 对四个明确目录逐项复制，并把任何 >=8 的 robocopy 返回码视为失败；不使用 `/MIR` 或删除参数。
203. 四个 torch 分发目录的同机复制全部完成，robocopy 均返回 1（成功复制新文件，低于失败阈值 8）；随后本任务 venv 首次 import torch 因尚未安装其声明依赖 `typing_extensions` 而退出码 1，这符合仅复制核心分发的预期，不是二进制错误。下一步在本任务 venv 安装仓库 requirements（包含/传递所需依赖），再安装与 torch 2.10 对应的官方 cu128 torchvision 0.25/torchaudio 2.10，最后才做隔离 import 与 pip check。
204. 本任务 venv 的首次 `pip install -r requirements.txt` 运行约 204.6 秒后失败，报 `No matching distribution found for timm>=1.0.15,<1.1`，且可用版本列表为空；这不是项目版本约束冲突，而是 pip 当前默认索引没有返回 PyPI 包。尚未安装 torchvision/torchaudio。下一步只读检查 pip config 与相关环境变量，然后显式指向官方 PyPI 重试其余依赖；torch CUDA wheel 仍保持已复制状态。
205. `pip config debug` 确认 global/site/user 均无自定义 pip.ini，未发现相关覆盖；显式查询 `https://pypi.org/simple` 在 39.1 秒内成功列出 timm 1.0.15–1.0.28 等版本，退出码 0，证明约束有效且官方 PyPI 可达，前次为空属于默认索引请求的临时失败。现在用显式官方 PyPI URL、长 timeout/retries 重试 requirements。
206. 显式 PyPI requirements 安装在本地 SSH 命令 304.1 秒超时前一直无错误输出；工具返回退出码 124，但这只证明客户端等待上限到达，不能据此判断远端 pip 是否被终止。未启动重复安装；立即只读检查远端进程命令行、已登记包与网络连接，再决定继续等待或恢复。
207. 客户端超时后只读检查确认 requirements pip 仍在 5090 运行：venv wrapper PID 14152、base Python PID 7032，命令行仍是唯一的官方 PyPI requirements 安装；当时累计写入约 2.2 MB，目标包均尚未登记。保持该单进程继续下载，不启动重复 pip。
208. 本地代码审查发现 train 的 `--eval-only` 仍用旧 flat test metrics，未保存结构化预测/PR，虽独立 evaluator 与训练结束路径已正确。为消除入口差异新增 `save_evaluation_artifacts` 契约测试；focused RED 在收集阶段因 helper 尚不存在而退出码 1。开始把 validation/test NPZ、validation PR 与冻结阈值 grouped metrics 收敛为训练结束和 eval-only 共用 helper。
209. 实现共用 `save_evaluation_artifacts`：固定写 validation/test 结构化 NPZ、validation PR 数组，并从 validation 校准唯一阈值生成 total/seen/unseen；无 test 时明确使用 0.5 而不伪造校准。train 结束与 `--eval-only` 已共同接入，评估/训练联合回归 `20 passed in 5.13s`、退出码 0。
210. 用上一轮 best checkpoint 实际运行 `--eval-only`，退出码 0；输出目录包含 runtime/git/config/manifest/environment、validation/test NPZ、validation PR 与 final metrics。validation 校准阈值仍为 0.248287，test 只使用该冻结阈值；total/seen/unseen 分组样本数正确为 4/2/2，验证 eval-only 端到端接线完成。
211. 5090 requirements pip 在 SSH 客户端超时后最终也结束，且目标依赖仍一个未登记；说明断开的前台 SSH 会话最终终止子进程，不能继续作为长下载载体。为避免再次受客户端时限影响，改用远端 `Start-Process` 直接启动 venv Python（不是嵌套 PowerShell），隐藏窗口并把 stdout/stderr 固定重定向到 `E:\OV-OrthKD-R0\installers\requirements-install.*.log`；后续只轮询该唯一 PID 与日志。
212. 首次发送“远端直接 Start-Process pip”包装命令时被本地工具策略在执行前拒绝，未到达 5090、未创建 PID 或日志。为避免继续在多层 shell 后台化上消耗时间，转而盘点本机已有 Python 3.11/Anaconda 依赖资产；优先打包可兼容的现有 wheels/site-packages 上传，缺失的小包再逐项远端安装。
213. 本机依赖盘点输出过长并被工具截断，但关键结果明确：官方 Python 3.11.9 只有 PyYAML 6.0.3、NumPy 2.4.6、Pillow 12.2、scikit-learn 1.9、tqdm/typing-extensions 等，Pillow 与 sklearn 超出仓库上界且缺 timm/pytest/transformers/open-clip 等；Anaconda 是 Python 3.13.9，二进制包不能复制到远端 CPython 3.11。pip show 还因本地 GBK 无法编码作者名产生大量 logging error，但命令退出码 0、没有环境变更。因此不采用整包本地复制；下一步检查 5090 已有 `uv`，利用其持久 cache/并发解析安装小型依赖。
214. 在 5090 定位到现有 `C:\Users\LXT\.local\bin\uv.exe`（约 51.1 MB），退出码 0；这是只读发现，不修改 uv 自身。使用 `uv pip install --python <本任务venv> -r requirements.txt --index-url https://pypi.org/simple`，让下载进入持久 uv cache 并利用并发/重试，目标仍严格是本任务隔离 venv。
215. `uv` 在 263.4 秒后明确失败：三次请求 `https://pypi.org/simple/numpy/` 均因响应体超时，退出码 1；没有依赖登记。根因进一步收敛为 5090 到官方 PyPI 的不稳定响应，而非 pip resolver。改用本机 CPython 3.11 从官方 PyPI 下载满足仓库上界的 Windows wheels 及明确的纯/二进制传递依赖到任务临时 wheelhouse，再通过已验证快速的 SCP 上传；torch 核心仍使用 5090 已验证的官方 cu128 分发。
216. 本机一次性 42 包 wheelhouse 下载同样在客户端 304 秒上限到达时被终止，退出码 124；与 pip 临时 torch 不同，已完成的独立 wheels 保留在 `AppData\Local\Temp\OVOrthKD-R0\wheelhouse-cp311`。下一步先统计落盘文件并按预期分发名求差集，只对缺项分小批次补下载。
217. 统计发现该 wheelhouse 实际仍为 0 文件，说明官方 PyPI 请求在首个 timm wheel 完成前就持续阻塞；本机 pip wheel cache 也没有相关可直接取出的分发。没有可上传资产。下一步检查本机由环境提供的默认只读 Python package proxy；若可用且快速，将其仅作为 PyPI 内容缓存获取 wheels，最终在 5090 通过包元数据/版本和 pip check 验证，不从未知模型/数据镜像取资源。
218. 本机未设置 PIP/UV 环境变量或 pip.ini，默认索引查询 timm 在 6.9 秒内成功；因此没有额外 package proxy 可利用，前次问题仍是偶发的大响应/下载阻塞。改为每次只下载一个或少量 wheel，先从 2.6 MB 的 timm 开始；每个成功文件立即持久化并记录，不再让一次大 resolver 请求决定整批成败。
219. 单包下载 timm 成功，退出码 0：复用了本机 HTTP cache 中的 `timm-1.0.28-py3-none-any.whl`，落盘 2,597,944 字节。策略验证有效，继续按二进制核心包和纯 Python 依赖分小批下载。
220. PyYAML/NumPy/Pillow/scikit-learn/SciPy 五包小批次再次在 304 秒上限终止，且未新增任何 wheel；pip 会先完成整批收集再保存，因此仍会被首个慢请求拖住。进一步收敛为严格单包下载；先取小型且本机已有的 PyYAML，再逐包处理二进制依赖。
221. 单包 PyYAML 下载成功，退出码 0，缓存 wheel 为 `pyyaml-6.0.3-cp311-cp311-win_amd64.whl`（158,763 字节）。wheelhouse 现有 timm 与 PyYAML 两项；继续单包 NumPy。
222. NumPy 单 wheel 在 304 秒上限内仍未完成并被终止，wheelhouse 未新增 NumPy；本机已有 CPython 3.11 NumPy 2.4.6 可作为满足 `<3` 的后备，但更优先尝试 5090 可达的高校 PyPI 缓存镜像。先用清华 TUNA 镜像仅安装 torch 必需的 `typing-extensions` 做连通/完整安装测试；若采用镜像，最终会记录完整版本并用 pip check/实际 import 验证，不从该镜像获取模型、数据或 checkpoint。
223. 5090 通过 TUNA + uv 在 0.3 秒级解析并安装 `typing-extensions 4.16.0`，总命令 29.3 秒、退出码 0；本任务隔离 venv 随即成功导入 `torch 2.10.0+cu128`，CUDA 12.8 可用，识别 RTX 5090/capability `[12,0]`。仅因 NumPy 尚未装出现预期 warning。镜像连通性验证通过，继续安装仓库 requirements；uv 因 cache/venv 位于不同磁盘自动回退 copy，不影响正确性。
224. 使用 TUNA + uv 安装完整 `requirements.txt` 成功，命令 23.3 秒、退出码 0：解析 43 包、下载/安装 41 包；关键版本为 timm 1.0.28、NumPy 2.4.6、Pillow 11.3.0、scikit-learn 1.6.1、pytest 8.4.2、transformers 4.57.6、open-clip-torch 2.32.0，均满足仓库约束。TUNA 同时提供了 PyPI torchvision 0.25.0；为确保与核心 torch 的 CUDA 12.8 构建完全一致，下一步从 PyTorch 官方 cu128 index 以 `--no-deps` 替换/补齐 torchvision 0.25.0+cu128 与 torchaudio 2.10.0+cu128。
225. PyTorch 官方 cu128 index 安装完成，命令 45.5 秒、退出码 0：下载 torchaudio 1.9 MiB、torchvision 8.9 MiB；卸载通用 PyPI torchvision 0.25.0，安装 `torchvision 0.25.0+cu128` 与 `torchaudio 2.10.0+cu128`，核心保持 `torch 2.10.0+cu128`。下一步执行本任务隔离 venv 的三包 import、CUDA capability、pip check，并在尚未同步任何本地修改前跑远端原始基线测试。
226. 5090 隔离 venv 验证全部通过：三包版本均为 2.10/0.25/2.10 `+cu128`，CUDA 12.8、cuDNN 91002，RTX 5090 capability `[12,0]`；`pip check` 输出 `No broken requirements found.`；尚未同步本地实现的远端基线完整 pytest 得到 `4 passed in 27.97s`，组合命令 55.4 秒、退出码 0。Task 1 的原始基线门槛满足。
227. 再次核验远端基线仓库：HEAD 精确为任务基线 `dca9f052fbe4a1e9d7982f24bdcec3edf1363fd4`，`git status --short` 无输出、退出码 0，证明前述 4 项测试确实运行在未修改源码上。现在才开始同步本地实现。
228. 从本地隔离 worktree 生成同步 ZIP，明确排除 `.git`、生成数据、outputs、pytest/pycache，仅包含代码/配置/测试/文档/报告；归档共 71 项、114,697 字节，SHA256 `01DC11ADCAD34464A08B3D7E0539A0D0A5850E54AE1EF30B054F8A7C4015AC69`。归档位于任务临时目录，不是最终产物。
229. 同步 ZIP 经 SCP 上传后，5090 复算 SHA256 完全一致并成功覆盖到保留 `.git` 的远端 repo；status 显示预期的大部分修改/新增文件。复核 status 发现 `src/data` 两个修改未出现：tar 的 `--exclude=data` 规则也匹配了嵌套 `src/data`，这是归档筛选过宽而非本地文件缺失。立即改为显式单独 SCP `src/data/__init__.py` 与 `src/data/ov_avel_dataset.py`，并在测试前重新核对远端 status。
230. 两个 `src/data` 文件单独 SCP 退出码 0；本地 SHA256 分别为 `3D7784D7C00FF84695027C81B71B01A7376FF8D0E9BB96F7C6A8B89D1518688A` 与 `A2518704CF5ABC33323E4920707263F24938FEC6978D7D2C8074DDE93D8C04F5`。下一条远端验证会先复算这两个 hash/status，再运行 compileall、完整 pytest 与 CUDA JSON。
231. 远端复算两个 data 文件 SHA256 与本地逐字一致，status 也完整出现 data 修改；compileall 通过。完整 pytest 得到 `55 passed, 3 failed in 11.49s`：三个失败全在 teacher identity 测试 fixture 的 `subprocess git init`，WinError 2 表明便携 Git 未加入 SSH PATH；不是 identity 逻辑失败。另有 48 条 Pillow 12 对 `Image.fromarray(..., mode="RGB")` 的弃用 warning。组合命令因 pytest 退出码 1 提前停止，CUDA 脚本尚未在这一条执行。修复 warning，并在远端验证命令显式加入已安装 Git cmd 后重跑。
232. 同步 warning 修复后，在 5090 SSH 会话显式加入便携 Git cmd，重新执行 `pip check`、compileall、完整 pytest、CUDA matmul 并保存环境证据，组合退出码 0：`No broken requirements found`；`58 passed in 14.31s` 且无此前 Pillow warning；CUDA JSON 为 Python 3.11.9、torch 2.10.0+cu128/CUDA 12.8/cuDNN 91002、RTX 5090 capability `[12,0]`、2048² fp16 五次平均 0.096512 ms、finite=true。远端已保存 CUDA JSON、排序 pip freeze 与 nvidia-smi 文本。
233. 继续读取上一条远程 smoke/preflight 长命令的异步单元时，工具返回 `cell 531 not found`，说明前一轮因输出超上下文而截断后单元句柄已关闭，不能据此判定预检成功或失败。首次只读检查远端产物/进程的 SSH 命令又因末尾多余反斜杠把 `Format-List\` 解析成不存在的命令而退出 1，未修改远端状态。下一步拆开为无嵌套格式化的短命令，以落盘 summary、退出状态线索和进程列表核验结果。
234. 使用 Base64 编码的短 PowerShell 只读核验成功执行：远端 `E:\OV-OrthKD-R0\outputs\r0_preflight` 不存在，且没有活动的 `preflight_ov_orthkd.py` 进程。因此前一条被截断的顺序命令没有到达或完成预检阶段，不能记为通过；将把 smoke、fixture、CUDA preflight 分别运行并各自保存 stdout/stderr 与退出码，避免再次因输出量丢失判据。
235. 在 5090 上单独运行 `scripts/smoke_test.py`，把完整输出保存到 `outputs/r0_evidence/smoke_test.log`；进程退出码 0，尾部明确为 `OV-OrthKD smoke test passed.`，基础模型/损失 smoke 通过。
236. 在 5090 上单独运行 `scripts/create_mm26_smoke_fixture.py --root .`，输出保存到 `outputs/r0_evidence/create_smoke_fixture.log`；退出码 0。train/val/test 各生成 4 条、每条 2 segment 的 mock-only 数据，三类教师工件全部启用，每个 split 编码 4 个唯一 query，未复制未重写的真实样本数均为 0。
237. 首次独立 CUDA preflight 在 5090 上退出 1，完整 traceback 已保存到 `outputs/r0_evidence/preflight_cuda.log`，且没有伪造 summary。失败发生在 camera-ready 文本对齐项：CUDA autocast 区域调用 `binary_cross_entropy(probability, target)` 被 PyTorch 2.10 明确拒绝为不安全。根因是现有 CPU 测试验证了映射余弦概率公式，却没有覆盖 CUDA AMP；修复原则是保持论文的 probability BCE 语义，只把该数值敏感项移入局部禁用 autocast 的 FP32 区域，而不是改成含义不同的 logits BCE。按 TDD 先新增 CUDA 回归测试并在 5090 观察 RED。
238. 新增 `test_paper_text_alignment_is_safe_inside_cuda_autocast`：以 CUDA fp16 输入在 autocast 内调用论文文本项，要求返回 FP32 有限损失且反向梯度有限。测试文件同步至 5090 后定向执行，按预期 `1 failed`，失败点与 preflight 完全相同，确认该测试能捕获实际回归而非环境噪声。
239. 在实现中为论文映射余弦概率 BCE 增加局部 `autocast(enabled=False)`，并将 query、text target、label 显式转为 FP32 后计算 cosine、clamp 与 probability BCE，梯度链保留。随后误用本机默认 Anaconda Python 运行 focused 测试，导入 NumPy/torch 时因已知的 MKL/OpenMP 本机环境冲突触发 `Fatal Python error: Aborted`，退出 1；这不是代码断言失败，也没有修改文件。后续 Python 验证继续只使用已隔离且通过基线的 5090 venv。
240. 将修复后的 loss 同步至 5090，定向运行原论文公式测试与新增 CUDA autocast/反向测试；结果 `2 passed in 5.21s`、退出码 0。说明修改同时保留 `(cos+1)/2` probability BCE 数值语义，并消除了 AMP 禁用错误且保持有限梯度。

## 2026-08-20

241. 修复后重新执行 5090 CUDA preflight，并在覆盖成功日志前把首次失败证据保留为 `preflight_cuda_failed_before_amp_fix.log`。本次退出码 0：train/val 各探测 4 样本、2 segments，强/弱/text 维度 512/768/1024；一次 AMP 训练探针总损失 1.614285（各项有限），val AP 0.775、test AP 0.666667；checkpoint 恢复出 epoch 1 与 best metric 0.775；CUDA 峰值显存 901.77 MB。生成的 188,951,028 字节 `preflight_resume.pt` 仅保留在 5090 outputs，不回传、不提交。
242. 在同一 RTX 5090、同一代码与模型配置上用 CUDA Event 同步测量效率，warmup 3、正式迭代 10：T=10 为 29.6897 ms/clip（33.6818 clips/s），T=16 为 30.2712 ms/clip（33.0347 clips/s）；两项退出码均为 0。模型可训练参数 46,278,129，visual 27,866,496，audio 8,687,086；JSON 分别保存在远端 evidence 目录。
243. 第一次手工验证 canonical full-run guard 时误传训练 CLI 不支持的 `--device cuda`，argparse 原始退出码 2，输出目录未创建；这次只验证了参数拒绝，不能作为归档阻断证据。已保留日志中的事实，立即去掉该参数，使用配置文件自身的 `device: cuda` 重跑并要求在数据/输出目录创建前因 archival facts 阻断。
244. 使用正确 CLI 重跑 canonical 配置：训练进程原始退出码 1，traceback 明确为 `Paper reproduction full run is blocked by unresolved archival facts`；包装验证同时确认预期输出目录根本未创建、日志含指定阻断文本，因此测试包装退出码 0。说明 canonical 路径在数据加载、模型构建与训练前 fail closed；前一次无效 CLI 日志另存，成功 guard 日志保留为 `canonical_block_guard.log`。
245. 在同步了最终 AMP 修复与 CUDA 回归测试的 5090 repo 上重跑完整核心矩阵并分别落盘：`pip check` 退出 0（`No broken requirements found.`）；`compileall -q src scripts tests` 退出 0；完整 pytest 退出 0，结果 `59 passed in 14.86s`。新增 CUDA 用例实际运行而非 skip，整套测试无失败、无 warning。
246. 回收 evidence 前检查文件列表与内容：13 个日志/JSON 均存在，`requirements-lock-5090.txt` 不含 `file://`、本机盘符或直接路径泄漏；但成功 preflight 日志开头暴露一条 PyTorch CUDA 警告，memory-efficient attention backward 默认非确定。根因定位到 `set_seed` 使用 `torch.use_deterministic_algorithms(True, warn_only=True)`，且未限制 CUDA SDPA 后端；因此上一条 pytest 虽全绿，尚不能把严格确定性标为完成。按系统化调试与 TDD，新增严格模式/SDPA 后端状态断言，先观察 RED，再修复为 fail-closed deterministic。
247. 扩展 seed 测试，要求 deterministic=true 时算法检查启用且非 warn-only、flash/memory-efficient SDPA 关闭、math SDPA 开启；另要求 deterministic=false 能恢复算法和三个 SDPA 后端。同步至 5090 定向运行后得到预期 `2 failed`：现实现仍为 warn-only，且从 true 切换 false 后算法全局开关未关闭。两个断言分别精确捕获日志警告和状态泄漏根因。
248. 修复 `set_seed`：deterministic=true 设置 `CUBLAS_WORKSPACE_CONFIG=:4096:8`、严格 `torch.use_deterministic_algorithms(..., warn_only=False)`、关闭 flash/memory-efficient SDPA 并只保留 math SDPA；false 分支显式关闭确定性算法并恢复全部 SDPA 后端，避免测试/多次运行间全局状态泄漏。同步至 5090 后两个 focused 测试 `2 passed in 6.01s`、退出码 0。
249. 在全新输出目录重跑严格确定性 CUDA preflight，退出码 0，且日志扫描 `Warning`、`non-deterministic`、`nondeterministic` 均无命中。一次训练探针总损失 1.6225866，val/test AP 0.5845238/0.5595238，恢复 best metric 0.5845238，CUDA 峰值显存 1345.26 MB；此前带非确定性 warning 的成功日志另存为对照，当前 `preflight_cuda.log` 只保留严格结果。
250. 为验证“设置了确定性开关”确实产生可重复运行，在另一个全新输出目录第二次执行同一 CUDA preflight；退出码 0、无 warning。解析两份 JSON 并逐值比较，train loss、val AP、test AP、resume best metric 完全相等（分别 1.6225866079330444、0.5845238095238094、0.5595238095238095、0.5845238095238094），`KEY_METRICS_EXACTLY_EQUAL=True`。
251. 严格确定性修复后的最终核心矩阵再次在 5090 执行：`pip check`、compileall、完整 pytest 原始退出码均为 0；pytest 为 `60 passed in 14.87s`，无失败、无 warning。远端 evidence 中的三份日志已覆盖为这一版最终结果。
252. 创建本地仓库 `reports/runtime/`，通过 SCP 回收 13 份小型证据：CUDA JSON、依赖锁、nvidia-smi、pip/compileall/pytest/smoke/fixture/canonical-guard 日志、T=10/T=16 效率 JSON，以及两次严格 preflight JSON。venv、pip/uv cache、mock 数据、checkpoint 和约 189 MB preflight checkpoint 均未回传。
253. 对回收文件逐个复算 SHA256 与大小；五份 JSON 均通过 PowerShell `ConvertFrom-Json` 解析，两份 preflight 分别 8,736/8,750 字节；全目录扫描未出现 `file://` 或 `@ file` 路径泄漏。零输出的 compileall 日志正确为 0 字节，其 SHA256 是标准空文件哈希；其成功退出码将在命令台账中独立记录。
254. 执行提交前工作树盘点：仍在隔离分支 `repro/r0-paper-faithfulness`、基线 HEAD 为 `dca9f052...`、origin 为 `https://github.com/rayyyyyyyyb/mm1.git`；所有修改均在 R0 目标文件，`git diff --check` 退出 0，仅显示 Git for Windows 的 LF→CRLF 信息性提示。确认本地 reports 已含静态教师身份、mock 工件审计和 13 份 5090 证据。
255. 新建 `reports/runtime/verification_commands.jsonl`，逐条记录最终 pip、compile、60 项 pytest、CUDA、smoke、fixture、两次严格 preflight、T=10/T=16 效率、canonical 阻断、mock audit、teacher identity 阻断和 `git diff --check` 的命令、原始/预期退出码与结果；文件采用 JSONL 且不包含环境缓存或凭据。
256. 新建 `reports/R0_REPRO_HARDENING_REPORT.md`：记录基线/分支、全部 P0/P1 修复映射、双模式与 loss 不变量、训练/评估安全、audit/provenance、5090 环境与逐命令结果、严格确定性复跑证据、六项 `BLOCKED_ARCHIVAL_FACT`、明确 `NOT_EXECUTED` 范围和完整文件清单。报告明确区分“R0 工程加固通过”与“论文真实数据尚未复现”，没有把 mock 数字冒充正式结果。
257. 进入收尾流程并完整读取 `verification-before-completion`、`finishing-a-development-branch`、`requesting-code-review` 技能。依照“fresh evidence before claims”要求，提交前还会在最终树上重跑完整验证；由于本轮系统明确禁止多代理，不能按 code-review skill 派生 reviewer，改为主代理逐文件/差异/敏感信息/任务清单自审。用户已明确要求上传 GitHub，因此集成选择已确定为保留隔离 worktree、创建单一分支提交并 push，不额外创建未经要求的 PR。执行计划已更新为仅剩最终自审、日志/任务书纳入、单提交与推送。
258. 按最终计划把外层权威 `all.md` 与原始任务书机械复制到仓库根目录；复制后逐文件 SHA256 完全一致：`all.md` 为 `8A4B8B54...E8A7980`，任务书为 `50EFE783...4C349`。这一步只是字节级同步，不改写内容；随后会在提交前再次同步更新后的外层日志。
259. 执行第一轮最终自审扫描：工作树只含任务范围内的代码/配置/测试/文档/报告；未发现私钥、GitHub token、API key、合并冲突标记或伪造弱教师 logits 模式；14 行 `verification_commands.jsonl` 全部可解析；仓库可见范围没有 `.pt/.pth/.ckpt/.npy/.npz` 等生成工件；`git diff --check` 退出 0。发现本地 `outputs/` 下有此前 bounded smoke 的三个约 566 MB checkpoint，但该目录已被 Git 忽略、status 不显示、不会暂存或上传，符合“实际运行产物可留扩刊、本轮不提交 checkpoint”的边界。
260. 用 `git check-ignore -v` 对实际大 checkpoint、mock manifest、teacher cache 精确复核：三份 checkpoint 均命中 `.gitignore:43 outputs/`，mock 数据与 teacher cache 命中 `.gitignore:33 data/*`；`git status --ignored` 也只以 `!!` 显示这些目录。检查退出码 0，确认后续 `git add -A` 不会把运行数据、模型工件或 cache 纳入提交。
261. 再次同步根目录 `all.md` 后执行 `git add -A` 并审查 45 个暂存文件；`git diff --cached --check` 退出 2，准确发现三类交付格式问题：原始任务书/报告/nvidia-smi 的行尾空格、两份设计文档 EOF 多空行，以及远端 PowerShell 重定向生成的四份 UTF-16 JSON 被 Git 识别为 binary。另有自写 numstat 排序器试图把 binary 的 `-` 转成整数而报错，但不影响 Git index。还发现 `*.log` 因通用 ignore 未暂存，而报告需要这些摘要。下一步只做机械格式修复：仓库副本去行尾空格/EOF 空行、运行证据统一 UTF-8 no-BOM，并显式 `git add -f reports/runtime/*.log`；不改变代码语义或外层原始任务书。
262. 完成机械交付格式修复：仓库内任务书副本、设计/计划、报告和 runtime 文本统一 LF、UTF-8 no-BOM，去除行尾空格与多余 EOF 空行；远程四份 JSON 现被 Git 识别为文本而非 binary。强制暂存了 6 份有价值的小型 `.log`（canonical guard、compileall、fixture、pip、pytest、smoke），没有 force-add 任何 outputs/data/checkpoint。重新 `git add` 后 `git diff --cached --check` 退出 0，runtime 14 个证据文件全部列为新增。
263. 按 branch-finishing 流程检测环境：这是 named linked worktree，git dir 位于主仓库 `.git/worktrees/OV-OrthKD-R0`，common dir 为主仓库 `.git`，工作树路径为 `扩刊/OV-OrthKD-R0`，分支为 `repro/r0-paper-faithfulness`；`main` 与当前 HEAD 的 merge-base 均精确为 `dca9f052...`，基线关系无歧义。暂存范围共 51 个文件，不含 outputs、raw/teacher data、venv/env/installers、checkpoint、zip 或 wheel；最大文件仅为约 90 KB 的日志副本。7 份 JSON 与 14 行 JSONL 均以显式 UTF-8 成功解析。
264. 为证明最终远端测试对应本地同一份代码，尝试构造“全部变更 Python/YAML/shell/README 的逐文件 SHA256 再聚合”检查；第一版仅在本地 PowerShell 解析阶段因嵌套字符串中的换行/引号转义错误退出 1，SSH 未发出、远端状态未变、也未得到 hash 结论。改用单引号 here-string 模板与占位符替换重新执行。
265. 第二版聚合脚本已在本地和远端各枚举同样的 30 个代码/配置文件，但两端旧版 .NET 均不提供 `[Convert]::ToHexString`，所以 aggregate 输出为空、比较为 false 并退出 1；逐文件读取无错误，未修改任何状态，但该轮仍不能作为一致性证据。第三版改用逐字节 `ToString('X2')` 生成兼容十六进制值。
266. 兼容版一致性核验成功：从暂存清单选择全部 30 个 Python/YAML/shell/README 代码配置文件，分别在本地与 5090 计算逐文件 SHA256，再对排序后的 `path|hash` 集合聚合；两端文件数均为 30，聚合 SHA256 均为 `43DFC46C7ED1862FD8B1AAAD188A8C8DA2AD8B1BC56ECC2867793AE82BBEE09C`，`AGGREGATES_MATCH=True`。因此最终 60 项 pytest 和严格 CUDA preflight 确实运行在与待提交代码逐字节一致的源码/配置上。
267. 依照 verification-before-completion 在准备提交的同一代码树上执行最后一次只读 5090 门禁，组合退出码 0：pip check 0、compileall 0、完整 pytest 0（`60 passed in 14.87s`）、smoke 0、CUDA runtime 0。CUDA 再次确认 torch 2.10.0+cu128、CUDA 12.8、cuDNN 91002、RTX 5090 `sm_120`、2048² FP16 finite=true，本轮计时 0.0964288 ms。该命令不覆盖已回收证据，因此本地 index 未发生运行产物变化。
268. 再次把权威日志同步进仓库并执行最终 index 审查：工作树相对 index 无未暂存差异，cached diff check 退出 0，51 个文件全部暂存，禁入路径/扩展名计数 0，仓库内外 `all.md` SHA256 同为 `453448D3...0F927`；提交前分支相对 main 的 commit 数仍为 0。最终 stat 为 51 files changed、7,799 insertions、321 deletions。
269. 只读核验 Git 提交与远端条件：本分支提交身份为 `Research Artifact <research-artifact@users.noreply.github.com>`；禁用交互提示后 `git ls-remote --heads origin refs/heads/repro/r0-paper-faithfulness` 退出 0 且无输出，确认目标远端分支尚不存在，不需要覆盖、rebase 或 force push。
270. 最终提交动作已具备全部前置证据：代码与 5090 聚合 hash 一致、最后门禁全为 0、index 范围/格式/敏感信息检查通过、目标远端分支不存在。现在把包含本条的权威日志最后一次同步并暂存，复核 cached diff 后创建任务书指定的唯一提交 `repro: harden paper-faithful OV-OrthKD baseline`；提交后不再 amend 以避免递归记录 commit 自身。
