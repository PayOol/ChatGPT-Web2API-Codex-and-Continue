// Exercise the actual converter shipped with the user's Continue extension.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname,'continue-stream-fixture.js'), 'utf8');
const start = source.indexOf('function fromChatCompletionChunk(chunk) {');
assert.ok(start >= 0, 'Continue converter not found');
const end = source.indexOf('\nfunction handleTextDeltaEvent(', start);
assert.ok(end > start, 'Continue converter boundary not found');
const convert = vm.runInNewContext(source.slice(start, end) + '\nfromChatCompletionChunk;');
const events = JSON.parse(fs.readFileSync(0, 'utf8'));
const messages = events.map(convert).filter(Boolean);
assert.equal(messages.map(m => m.content || '').join(''), 'Je vais commencer par le README.');
const calls = messages.flatMap(m => m.toolCalls || []);
assert.equal(calls.length, 1, 'Continue lost the tool call accompanying the commentary');
assert.equal(calls[0].function.name, 'read_file');
assert.equal(JSON.parse(calls[0].function.arguments).path, 'demo.py');
assert.equal(events.at(-1).choices[0].finish_reason, 'tool_calls');
console.log('Installed Continue converter preserved commentary AND tool call');
