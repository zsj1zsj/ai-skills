# Trip Plan 便携安装包

功能：中文交互问卷 → 三路资料研究 → 四季/日期行程编排与审阅 → 真实景点照片 → 可选餐饮店 → 单文件离线 HTML。

本包是用户目录资源安装包，不是独立应用，不要直接把 ZIP 传给 `pi install`。先完整解压，再使用下面的安装器。技能并不局限于厦门；包内没有个人旅行需求或旧报告。

## 1. 另一台电脑的前提

- 已安装 Pi coding agent；本次源环境 Pi **0.84.2**、Node.js **22.23.2**（该 Pi 要求 Node >=22.19.0）。其他版本需实际验证。
- Python **3.13**（源环境3.13.14）；脚本只使用标准库，不需要 pip 安装库。应能执行 `python --version`（macOS/Linux通常用 `python3`）。
- 安装并在 **Herdr** 中运行 Pi，使 `HERDR_ENV=1`；需要 **pi-herdr-agents** 提供 subagent 工具。本次使用2.0.4。它们未随ZIP分发，也不由本安装器联网安装。
- 若尚未安装子代理扩展，在 Pi 支持的终端执行 `pi install npm:pi-herdr-agents`，按该扩展及 Herdr 官方说明完成配置，并实际测试一个子代理。新版扩展兼容性需另测。
- 在目标电脑自行登录/配置可用模型。当前技能及五角色固定使用 **openai-codex/gpt-6-astra**；必须确认这个精确模型实际可访问，不能只看模型列表。ZIP不包含登录状态、token、API key或模型配置。若目标电脑没有这个模型，应先统一修改技能中的调用要求与五个角色的model字段为目标环境实际可用模型，不能仅改一处或假定自动回退。
- Windows额外需要 Git for Windows / Git Bash。若子代理误启动WSL，见 `compatibility/windows-launch/README.md`；本包不会自动修改第三方安装。
- 研究和取图需要能访问公共网页、Wikimedia Commons、Open-Meteo等；无网络时无法保证新资料/图片。预览图优先但不是强制凑图；餐饮通常3–5家，证据不足会明确说明。

## 2. 安装（推荐）

先退出或结束目标电脑正在进行的Pi任务。将ZIP完整解压到普通本地目录，在有 `install.py` 的目录打开终端。

Windows PowerShell：

```powershell
python .\install.py --dry-run
python .\install.py
```

若只有Python Launcher，可改用 `py -3.13` 替代 `python`。macOS/Linux：

```sh
python3 ./install.py --dry-run
python3 ./install.py
```

默认目标为 `~/.pi/agent/`；如果设置了 `PI_CODING_AGENT_DIR` 则使用该目录。显式目标：

```powershell
python .\install.py --target "D:\PiProfile\agent" --dry-run
python .\install.py --target "D:\PiProfile\agent"
```

已有同名但内容不同的文件时，默认拒绝覆盖。先检查冲突，确认要替换才运行：

```powershell
python .\install.py --overwrite
```

覆盖前旧文件会完整备份到目标目录 `.trip-plan-install-backups/<时间>/`，加 `.bak` 后缀，不会误加载为角色。特别注意 `researcher` 等五个角色名较通用，替换会影响其他使用同名角色的工作流；项目级同名角色还可能覆盖全局角色，需自行检查。安装器不会改settings、账号、其他文件，不联网，不应用Windows补丁。校验清单用于检测传输损坏，不是发行签名或沙箱；执行前请审查代码。

安装后在Pi执行 **`/reload`**，或退出并从Herdr重新启动Pi。环境变量变化需要重启进程。

## 3. 使用

- 在Pi输入 **`/trip-plan`**，逐项填写并确认弹窗问卷；Esc可取消。
- `/skill:trip-plan` 也由问卷扩展处理。
- 已有确认需求时，可以直接说“按之前需求重新生成旅游攻略，配上景点预览图和餐饮候选”，避免重新问卷。
- 工作项目中的输出路径：`.pi/plans/<日期-目的地>/trip.html`；实际运行可另加版本后缀。
- 成功获取的照片会嵌入HTML，不依赖远程图片；原始照片、来源、许可、请求失败会记录在运行资料中。来源超链接本身仍需网络。
- 餐饮是分片区的候选卡片，不强制预约或全部打卡；营业、菜单及节日安排以临行核实为准。

## 4. 安装后的本地自检

默认安装位置，Windows PowerShell：

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -B -m unittest discover -s "$HOME/.pi/agent/skills/trip-plan/tests" -p "test_*.py"
node --experimental-strip-types "$HOME/.pi/agent/skills/trip-plan/tests/questionnaire.mjs"
```

macOS/Linux：

```sh
PYTHONIOENCODING=utf-8 python3 -B -m unittest discover -s "$HOME/.pi/agent/skills/trip-plan/tests" -p 'test_*.py'
node --experimental-strip-types "$HOME/.pi/agent/skills/trip-plan/tests/questionnaire.mjs"
```

自定义目标请替换测试路径。Python测试含mock网络、安全拒绝、取图→嵌入→报告检查、餐饮引用与页面检查。它们不能代替目标电脑的模型认证、Herdr子代理启动、真实联网和浏览器测试。

## 5. 内容结构

```text
install.py
payload-manifest.json             # 每个安装文件的SHA-256
payload/
  extensions/trip-plan.ts          # 原生问卷扩展
  agents/                         # 五个旅行角色
  skills/trip-plan/
    SKILL.md
    references/contracts.md
    scripts/                      # 校验、真实取图、嵌图
    tests/
compatibility/windows-launch/     # 可选兼容参考，不自动安装
```

只想手工安装时，将 `payload/` 下的三个目录合并到 `~/.pi/agent/`，保持相对层级：扩展会相对定位 `../skills/trip-plan/SKILL.md`，问卷测试也依赖这个布局。必须先备份同名文件。不要把整个 `payload` 文件夹再套在 `agent` 下面，也不要只复制SKILL.md。

## 6. 已验证与边界

源环境中：72项Python测试通过、问卷测试通过；实际取图、离线嵌入及4家餐饮卡报告生成成功。此次打包还会在独立解压目录复跑测试，并验证安装器的新装、重复安装、冲突拒绝与备份覆盖。未在另一台物理电脑上测试，未做浏览器视觉回归。

便携版测试仅移除了“源电脑某日必须恰有7个历史备份”的本机维护断言，其余测试保留；运行时技能及扩展未因此改动。

包内不含凭据、个人配置、node_modules、缓存、历史备份、旧攻略或第三方照片。本地安装器没有完整卸载命令：移除时仅删除本包安装文件，若原先有同名文件，按备份恢复，不要删除整个agents或extensions目录。
