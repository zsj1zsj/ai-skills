/** /trip-plan and /skill:trip-plan: native Pi dialogs before any model research.
 * Global extension. Reload with /reload after editing.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const SKILL_PATH = fileURLToPath(new URL("../skills/trip-plan/SKILL.md", import.meta.url));
const CUSTOM = "自定义…";
type Field = { key: string; label: string; hint?: string; options?: string[]; date?: boolean };
const fields: Field[] = [
  { key: "destination", label: "目的地", hint: "例如：厦门" },
  { key: "origin", label: "出发城市", hint: "例如：上海；未定填待定" },
  { key: "start", label: "开始日期", hint: "YYYY-MM-DD，或待定", date: true },
  { key: "end", label: "结束日期", hint: "YYYY-MM-DD，或待定", date: true },
  { key: "party", label: "同行人数和年龄", hint: "例如：2 位成人（30 岁），1 位孩子（6 岁）" },
  { key: "budget", label: "人均预算档次", options: ["经济", "舒适", "高端", "待定", CUSTOM] },
  { key: "budget_scope", label: "预算包含哪些费用？", options: ["含往返交通、住宿及当地消费", "仅当地消费及住宿，不含往返交通", "仅当地消费，不含交通和住宿", "待定", CUSTOM] },
  { key: "pace", label: "行程节奏", options: ["轻松：多休息、少赶路", "适中：游玩与休息平衡", "紧凑：尽量多玩", CUSTOM] },
  { key: "interests", label: "主要兴趣（组合偏好可选自定义）", options: ["海边休闲 + 美食", "人文建筑 + 历史", "拍照 + 城市漫步", "亲子体验", "自然风光", CUSTOM] },
  { key: "must", label: "必去／不想去的地方", hint: "没有填无，未定填待定" },
  { key: "needs", label: "忌口、行动限制及其他硬要求", hint: "例如：不吃海鲜、不早起、不能长走；没有填无" },
  { key: "bookings", label: "已订交通／酒店及抵离时间", hint: "未订填未订；已订请写时间、地点" },
];

export function validDate(value: string): boolean {
  if (value === "待定") return true;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

async function ask(ctx: ExtensionContext, field: Field, previous?: string): Promise<string | undefined> {
  for (;;) {
    let value: string | undefined;
    if (field.options) {
      value = await ctx.ui.select(field.label, field.options);
      if (value === CUSTOM) value = await ctx.ui.input(`${field.label}（自定义）`, previous ?? "请输入具体要求");
    } else {
      value = await ctx.ui.input(field.label, previous ?? field.hint);
    }
    if (value === undefined) return undefined;
    value = value.trim();
    if (!value) {
      ctx.ui.notify("请填写内容；未确定可填待定，Esc 取消整个问卷。", "warning");
      continue;
    }
    if (field.date && !validDate(value)) {
      ctx.ui.notify("请输入有效日期 YYYY-MM-DD，或填待定。", "warning");
      continue;
    }
    return value;
  }
}

export default function tripPlanExtension(pi: ExtensionAPI) {
  let running = false;
  async function prepare(args: string, ctx: ExtensionContext): Promise<string | undefined> {
    if (running) {
      ctx.ui.notify("旅行问卷已打开，请先完成或取消。", "warning");
      return;
    }
    if (!ctx.isIdle()) {
      ctx.ui.notify("请等当前任务结束后再打开旅行问卷。", "warning");
      return;
    }
    running = true;
    try {
      const body = readFileSync(SKILL_PATH, "utf8").replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n*/, "").trim();
      const wrap = (text: string) => `<skill name="trip-plan" location="${SKILL_PATH}">\n${body}\n</skill>\n\n${text}`;
      if (!ctx.hasUI) {
        return wrap(`${args}\n当前环境无交互 UI，请用文字逐项收集缺失信息，再确认 brief；不要假装已完成弹窗确认。`);
      }
      ctx.ui.notify("先逐项填写旅行需求，最后确认；Esc 可取消，不启动研究。", "info");
      const answers: Record<string, string> = {};
      // Preserve arbitrary command arguments verbatim rather than guessing their meaning.
      if (args.trim()) answers.original_request = args.trim();
      const cancel = () => { ctx.ui.notify("已取消旅行问卷，未启动研究。", "info"); return undefined; };
      for (const field of fields) {
        const value = await ask(ctx, field);
        if (value === undefined) return cancel();
        answers[field.key] = value;
      }
      for (;;) {
        if (answers.start !== "待定" && answers.end !== "待定" && answers.end < answers.start) {
          ctx.ui.notify("结束日期不能早于开始日期，请重新填写结束日期。", "warning");
          const value = await ask(ctx, fields[3], answers.end);
          if (value === undefined) return cancel();
          answers.end = value;
          continue;
        }
        const summary = [
          ...(answers.original_request ? [`原始需求：${answers.original_request}`] : []),
          ...fields.map(f => `${f.label}：${answers[f.key]}`),
        ].join("\n");
        const action = await ctx.ui.select(`确认旅行需求\n${summary}`, ["确认并继续", "修改某一项", "取消"]);
        if (action === undefined || action === "取消") return cancel();
        if (action === "修改某一项") {
          const label = await ctx.ui.select("要修改哪一项？", [...fields.map(f => f.label), "原始需求", "返回确认"]);
          if (label === undefined) return cancel();
          if (label === "返回确认") continue;
          const field = fields.find(f => f.label === label) ?? { key: "original_request", label: "原始需求" };
          const value = await ask(ctx, field, answers[field.key]);
          if (value === undefined) return cancel();
          answers[field.key] = value;
          continue;
        }
        return wrap("以下需求已由用户在交互问卷中逐项填写并确认。不要重复发送整套问题。\n" +
          "先按契约写 brief.json；这些是问卷原始答案，不是 brief.json 契约对象。" +
          "待定值应保留为未知，不得猜测。若目的地、日期等关键条件未定，或原始需求与答案冲突，" +
          "仅澄清阻塞项，确认之前不要启动研究。无阻塞则继续 Phase 1。\n" + JSON.stringify(answers, null, 2));
      }
    } catch (error) {
      ctx.ui.notify(`旅行问卷失败：${error instanceof Error ? error.message : String(error)}`, "error");
      return;
    } finally {
      running = false;
    }
  }

  pi.registerCommand("trip-plan", {
    description: "交互式旅行问卷 → 资料研究 → HTML 行程报告",
    handler: async (args, ctx) => {
      const message = await prepare(args, ctx);
      if (message) pi.sendUserMessage(message, { deliverAs: "followUp" });
    },
  });
  pi.on("input", async (event, ctx) => {
    if (event.source === "extension") return { action: "continue" };
    const match = event.text.match(/^\/skill:trip-plan(?:\s+([\s\S]*))?$/);
    if (!match) return { action: "continue" };
    const message = await prepare(match[1] ?? "", ctx);
    return message ? { action: "transform", text: message, images: event.images } : { action: "handled" };
  });
}
