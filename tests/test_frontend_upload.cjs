const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function page() {
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
  const requests = [], jobs = [];
  class XHR {
    constructor() { this.upload = {}; requests.push(this); }
    open(method, url) { this.method = method; this.url = url; }
    send(body) { this.body = body; }
  }
  const context = vm.createContext({
    document: {getElementById: id => elements.get(id), createElement: element, body: element()},
    XMLHttpRequest: XHR, FormData: class {append() {}},
    fetch: url => url === '/upload' ? new Promise(() => {}) : Promise.resolve({json: () => Promise.resolve([])}),
    alert: message => assert.fail('Unexpected alert: ' + message), setTimeout() {},
  });
  const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  vm.runInContext('render = j => recordedJobs.push(j)', Object.assign(context, {recordedJobs: jobs}));
  return {context, requests, jobs, box: elements.get('jobs')};
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
