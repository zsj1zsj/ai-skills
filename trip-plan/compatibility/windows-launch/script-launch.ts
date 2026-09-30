import { existsSync } from "node:fs";
import { win32 } from "node:path";

/** Never resolve bare bash through Windows PATH: it may be the WSL launcher. */
export function scriptLaunchCommand(
	scriptPath: string,
	platform: string = process.platform,
	env: NodeJS.ProcessEnv = process.env,
	exists: (path: string) => boolean = existsSync,
): string {
	if (platform !== "win32") {
		return "bash '" + scriptPath.replace(/'/g, "'\\''") + "'";
	}
	const override = env.PI_HERDR_GIT_BASH;
	const roots = [
		env.ProgramFiles || "C:\\Program Files",
		env["ProgramFiles(x86)"],
		env.LOCALAPPDATA && win32.join(env.LOCALAPPDATA, "Programs"),
	].filter((root): root is string => Boolean(root));
	const candidates = override
		? [override]
		: roots.map((root) => win32.join(root, "Git", "bin", "bash.exe"));
	const bash = candidates.find((path) => win32.isAbsolute(path) && exists(path));
	if (!bash) {
		throw new Error(
			"Git Bash not found. Install Git for Windows or set PI_HERDR_GIT_BASH to its absolute bash.exe path, then restart Pi.",
		);
	}
	// EncodedCommand works from PowerShell, cmd and Git Bash. It avoids nesting
	// POSIX quotes in PowerShell and protects spaces, apostrophes and Unicode.
	const quote = (value: string) => "'" + value.replace(/'/g, "''") + "'";
	const source = `& ${quote(bash.replace(/\\/g, "/"))} -- ${quote(scriptPath.replace(/\\/g, "/"))}; exit $LASTEXITCODE`;
	return `powershell.exe -NoLogo -NoProfile -EncodedCommand ${Buffer.from(source, "utf16le").toString("base64")}`;
}
