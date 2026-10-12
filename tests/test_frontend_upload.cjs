const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function page(options = {}) {
  const elements = new Map();
  function element() {
    return {
      className: '', style: {}, textContent: '', children: [],
      set innerHTML(html) {
        this.children = [...html.matchAll(/class="([^"]+)"/g)].map(match => {
          const child = element(); child.className = match[1]; return child;
        });
      },
      appendChild(child) { this.children.push(child); },
      prepend(child) { this.children.unshift(child); },
      remove() { elements.get('jobs').children = elements.get('jobs').children.filter(x => x !== this); },
      addEventListener() {}, classList: {add() {}, remove() {}},
      querySelector(selector) {
        const className = selector.slice(1);
        function find(node) {
          if (node.className.split(' ').includes(className)) return node;
          for (const child of node.children) { const found = find(child); if (found) return found; }
        }
        return find(this);
      },
    };
  }
  for (const id of ['drop', 'jobs', 'go']) elements.set(id, element());
  const requests = [], jobs = [], timers = [];
  class XHR {
    constructor() { this.upload = {}; requests.push(this); }
    open(method, url) { this.method = method; this.url = url; }
    send(body) { this.body = body; }
  }
  const context = vm.createContext({
    document: {getElementById: id => elements.get(id) || elements.get('jobs').children.find(el => el.id === id), createElement: element, body: element()},
    XMLHttpRequest: XHR, FormData: class {append() {}},
    fetch: (url, init) => url === '/jobs' ? Promise.resolve({json: () => Promise.resolve([])}) : options.fetch ? options.fetch(url, init) : new Promise(() => {}),
    confirm: () => options.confirm !== false,
    alert: message => assert.fail('Unexpected alert: ' + message), setTimeout(fn, delay) { timers.push({fn, delay}); },
  });
  const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  if (!options.keepRender) vm.runInContext('render = j => recordedJobs.push(j)', Object.assign(context, {recordedJobs: jobs}));
  return {context, requests, jobs, timers, box: elements.get('jobs')};
}

test('file upload is visible and animated before the server responds', () => {
  const p = page();
  vm.runInContext('send({name:"lecture.mp4"})', p.context);
  assert.equal(p.box.children.length, 1);
  const card = p.box.children[0];
  assert.match(card.className, /uploading/);
  assert.equal(card.querySelector('.name').textContent, 'lecture.mp4');
  assert.match(card.querySelector('.st').textContent, /Загрузка/);
  assert.equal(p.requests[0].url, '/upload');
  p.requests[0].upload.onprogress({lengthComputable: true, loaded: 25, total: 100});
  assert.match(card.querySelector('.st').textContent, /25%/);
  assert.equal(card.querySelector('.fill').style.width, '25%');
  p.requests[0].upload.onload();
  assert.match(card.querySelector('.st').textContent, /ожидаю/);
  assert.match(card.className, /uploading/);
  p.requests[0].status = 200;
  p.requests[0].responseText = '{"id":"abc","filename":"lecture.mp4"}';
  p.requests[0].onload();
  assert.equal(p.box.children.length, 0);
  assert.equal(p.jobs[0].id, 'abc');
});

test('concurrent uploads have independent progress', () => {
  const p = page();
  vm.runInContext('send({name:"a.mp3"}); send({name:"b.mp3"})', p.context);
  assert.equal(p.box.children.length, 2);
  p.requests[0].upload.onprogress({lengthComputable: true, loaded: 50, total: 100});
  assert.match(p.box.children[1].querySelector('.st').textContent, /50%/);
  assert.doesNotMatch(p.box.children[0].querySelector('.st').textContent, /50%/);
});

for (const failure of ['http', 'network', 'abort', 'invalid-json']) {
  test(`upload ${failure} failure replaces animation with a visible error`, () => {
    const p = page();
    vm.runInContext('send({name:"a.mp3"})', p.context);
    const xhr = p.requests[0];
    if (failure === 'http') { xhr.status = 400; xhr.responseText = 'unsupported format'; xhr.onload(); }
    if (failure === 'network') xhr.onerror();
    if (failure === 'abort') xhr.onabort();
    if (failure === 'invalid-json') { xhr.status = 200; xhr.responseText = '<html>error</html>'; xhr.onload(); }
    assert.match(p.box.children[0].className, /error/);
    assert.doesNotMatch(p.box.children[0].className, /uploading/);
    assert.match(p.box.children[0].querySelector('.st').textContent, /Ошибка/);
    assert.equal(p.jobs.length, 0);
  });
}


for (const status of ['done', 'error', 'transcribing']) {
  test(`history ${status} card offers deletion only for finished jobs`, async () => {
    const p = page({keepRender: true, fetch: async () => ({ok: true, json: async () => ({status, progress: 50, phrases: 1})})});
    await vm.runInContext('render({id:"1234abcd", filename:"a.mp3"})', p.context);
    assert.equal(Boolean(p.box.children[0].querySelector('.delete')), status !== 'transcribing');
  });
}

for (const outcome of ['success', 'cancel', 'http-error', 'network-error', 'already-deleted']) {
  test(`history deletion handles ${outcome}`, async () => {
    const calls = [];
    const p = page({keepRender: true, confirm: outcome !== 'cancel', fetch: async (url, init) => {
      if (!init) return {ok: true, json: async () => ({status:'done', progress:100, phrases:1})};
      calls.push([url, init.method]);
      if (outcome === 'network-error') throw new Error('offline');
      return {ok: outcome === 'success', status: outcome === 'already-deleted' ? 404 : 500, json: async () => ({detail:'denied'})};
    }});
    await vm.runInContext('render({id:"1234abcd", filename:"a.mp3"})', p.context);
    const card = p.box.children[0], button = card.querySelector('.delete');
    await button.onclick();
    if (outcome === 'cancel') {
      assert.equal(calls.length, 0);
      assert.equal(p.box.children.length, 1);
    } else {
      assert.deepEqual(calls, [['/jobs/1234abcd', 'DELETE']]);
      if (outcome === 'success' || outcome === 'already-deleted') assert.equal(p.box.children.length, 0);
      else {
        assert.equal(p.box.children.length, 1);
        assert.equal(button.disabled, false);
        assert.match(card.querySelector('.delete-error').textContent, /Не удалось удалить/);
      }
    }
  });
}


for (const status of [404, 503]) {
  test(`history polling handles HTTP ${status} without losing recovery`, async () => {
    const p = page({keepRender: true, fetch: async () => ({ok: false, status})});
    await vm.runInContext('render({id:"1234abcd", filename:"a.mp3"})', p.context);
    assert.equal(p.box.children.length, status === 404 ? 0 : 1);
    assert.equal(p.timers.length, status === 404 ? 0 : 1);
    if (status === 503) assert.equal(p.timers[0].delay, 2000);
  });
}
