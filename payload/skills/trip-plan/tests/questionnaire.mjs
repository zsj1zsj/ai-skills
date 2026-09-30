import assert from 'node:assert/strict';
import extension, { validDate } from '../../../extensions/trip-plan.ts';

assert.equal(validDate('2028-02-29'), true);
for (const value of ['2027-02-29', '2027-13-01', '2027-2-01', '']) assert.equal(validDate(value), false);
assert.equal(validDate('待定'), true);

const inputs = ['厦门', '上海', '2027-05-01', '2027-05-04', '2 成人，30 岁', '无', '无', '未订'];
const selections = ['舒适', '含往返交通、住宿及当地消费', '适中：游玩与休息平衡', '海边休闲 + 美食', '确认并继续'];
function harness({input = [...inputs], select = [...selections], hasUI = true, idle = true} = {}) {
  let command, hook;
  const sent = [], notes = [];
  extension({registerCommand: (_, c) => command = c.handler, on: (_, h) => hook = h, sendUserMessage: text => sent.push(text)});
  const ctx = {hasUI, isIdle: () => idle, ui: {
    input: async () => { assert.ok(input.length, 'unexpected input'); return input.shift(); },
    select: async () => { assert.ok(select.length, 'unexpected select'); return select.shift(); },
    notify: (...args) => notes.push(args),
  }};
  return {run: args => command(args, ctx), hook: event => hook(event, ctx), sent, notes};
}
let h = harness();
await h.run('厦门旅游');
assert.equal(h.sent.length, 1);
assert.ok(h.sent[0].includes('"original_request": "厦门旅游"'));
assert.ok(h.sent[0].includes('"destination": "厦门"'));

// Esc at every input/selection must never start research.
for (let i = 0; i < inputs.length; i++) {
  const values = [...inputs]; values[i] = undefined;
  h = harness({input: values}); await h.run(''); assert.equal(h.sent.length, 0);
}
for (let i = 0; i < selections.length; i++) {
  const values = [...selections]; values[i] = undefined;
  h = harness({select: values}); await h.run(''); assert.equal(h.sent.length, 0);
}
h = harness({select: [...selections.slice(0, -1), '取消']});
await h.run(''); assert.equal(h.sent.length, 0);
h = harness({select: [...selections.slice(0, -1), '修改某一项', '目的地', '确认并继续'], input: [...inputs, '泉州']});
await h.run(''); assert.ok(h.sent[0].includes('"destination": "泉州"'));

h = harness({input: ['厦门', '上海', '2027-05-05', '2027-05-04', ...inputs.slice(4), '2027-05-07']});
await h.run(''); assert.ok(h.sent[0].includes('"end": "2027-05-07"'));
h = harness({select: ['自定义…', ...selections.slice(1)], input: [...inputs.slice(0, 5), '3000 元硬上限', ...inputs.slice(5)]});
await h.run(''); assert.ok(h.sent[0].includes('3000 元硬上限'));
h = harness({hasUI: false}); await h.run('厦门'); assert.ok(h.sent[0].includes('当前环境无交互 UI'));
h = harness({idle: false}); await h.run(''); assert.equal(h.sent.length, 0);
h = harness();
assert.equal((await h.hook({source: 'interactive', text: '/skill:trip-plan 厦门'})).action, 'transform');
assert.equal(h.sent.length, 0);
assert.equal((await h.hook({source: 'extension', text: '/skill:trip-plan'})).action, 'continue');
assert.equal((await h.hook({source: 'interactive', text: '/skill:trip-plan-other'})).action, 'continue');
console.log('PASS: dates, submission, all cancellation points, editing, reversed dates, custom budget, no UI, busy guard, skill routing.');
