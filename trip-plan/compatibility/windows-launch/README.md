# Windows 子代理启动兼容参考（可选，不自动安装）

如果目标电脑的 pi-herdr-agents 已正确调用 Git Bash，不要应用本补丁。这里仅保留本机使用的兼容改动，供遇到相同问题时审查；不是完整第三方包，也不是跨版本安装器。

症状：子代理终端出现 `WSL ERROR ... execvpe(/bin/bash) failed`，即裸 `bash` 被Windows解析成WSL启动器，而不是Git Bash。

本机 pi-herdr-agents 2.0.4 的修复方式：
1. 安装Git for Windows，确认真正的 `Git/bin/bash.exe` 存在。
2. 备份目标机器 pi-herdr-agents 包中的 `pi-extension/subagents/terminal.ts`。
3. 人工比较本目录 `terminal.ts.patch` 和目标文件。只有对应启动逻辑一致时才应用这份小改动；不要将本机完整旧terminal文件覆盖另一版本。
4. 将这里的 `script-launch.ts` 放到包的 `pi-extension/subagents/`，与terminal.ts同级。补丁只改为使用该函数。
5. 函数显式查找Git Bash，并通过PowerShell EncodedCommand处理Windows路径与引号。标准位置找不到时，在启动Herdr/Pi之前设置绝对路径，例如PowerShell：

```powershell
$env:PI_HERDR_GIT_BASH = "C:\Program Files\Git\bin\bash.exe"
```

这不是永久环境变量配置；必须让新启动的Herdr/Pi进程继承它。随后重启并实际运行一个子代理。

macOS/Linux通常不需要此补丁。第三方包升级可能覆盖本地补丁；不要盲目重复应用。包的位置取决于全局/项目安装或自定义配置，本文不硬编码用户目录。若新版包已经具备修复，应使用新版自带实现。
