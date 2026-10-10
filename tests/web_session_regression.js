/* Deterministic delayed-body checks against the actual browser script. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');

function harness(status, formValues=[['title','fixture']]) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      hidden: false, open: false, textContent: '', value: '', resetCount: 0,
      listeners: {}, addEventListener(type, callback) { this.listeners[type] = callback; },
      querySelector() { return element(id + '-button'); },
      replaceChildren() {}, reset() { this.resetCount++; },
    });
    return elements.get(id);
  }
  let releaseBody, bodyStarted;
  const started = new Promise(resolve => { bodyStarted = resolve; });
  const body = new Promise(resolve => { releaseBody = resolve; });
  const storage = new Map();
  const context = vm.createContext({
    document: {getElementById: element, querySelectorAll: () => [], activeElement: null},
    sessionStorage: {getItem: key => storage.get(key), setItem: (key,value) => storage.set(key,value), removeItem: key => storage.delete(key)},
    setTimeout: () => 1, clearTimeout() {}, AbortController, Date, JSON,
    location: {origin:'http://127.0.0.1:1'},
    FormData: class { *[Symbol.iterator]() { yield* formValues; } },
    fetch: async () => ({status, ok:status===200, json: () => {bodyStarted();return body;}}),
  });
  vm.runInContext(source, context);
  const run = code => vm.runInContext(code, context);
  const switchSession = () => run("generation++; token='new-session'; sessionStorage.setItem('crewmesh_web_token',token)");
  return {element, run, switchSession, started, releaseBody, storage};
}

(async () => {
  // A response can deliver headers before logout and its JSON body afterwards.
  // Neither a stale 401 nor a stale success may affect the replacement session.
  for (const status of [401,200]) {
    const h = harness(status);
    h.run("token='old-session'");
    const result = h.run("api('/api/snapshot').catch(error => error.message)");
    await h.started;
    h.switchSession();
    h.releaseBody({message:'expired', me:{room_id:'old-room'}});
    assert.equal(await result, '访问已切换');
    assert.equal(h.run('token'), 'new-session');
    assert.equal(h.storage.get('crewmesh_web_token'), 'new-session');
  }
  for (const name of ['create','join']) {
    const h = harness(200), form = h.element('form-'+name);
    const completion = form.listeners.submit({preventDefault(){},currentTarget:form});
    await h.started;
    h.switchSession();
    h.releaseBody({web_token:'old-created-token',agent_token:'old-agent-token'});
    await completion;
    assert.equal(h.run('token'), 'new-session');
    assert.equal(h.element('private-dialog').open, false);
    assert.equal(form.resetCount, 0);
  }
  // Resolve JSON, then switch in the same microtask turn: api has already
  // passed its final generation guard, but the form continuation has not run.
  const restore = harness(200, [['web_token','restore-session']]);
  restore.run(`const originalApi = api;
    api = async (...args) => {
      const result = await originalApi(...args);
      generation++; token='new-session';
      sessionStorage.setItem('crewmesh_web_token', token);
      return result;
    };`);
  const restoreForm = restore.element('form-restore');
  const restored = restoreForm.listeners.submit({preventDefault(){},currentTarget:restoreForm});
  await restore.started;
  restore.releaseBody({me:{room_id:'old-room'}});
  await restored;
  assert.equal(restore.run('token'), 'new-session');
  assert.equal(restore.storage.get('crewmesh_web_token'), 'new-session');
  assert.equal(restoreForm.resetCount, 0);
  const h = harness(200), form = h.element('task-form');
  h.run("token='old-session'");
  form.listeners.submit({preventDefault(){},currentTarget:form});
  await h.started;
  h.switchSession();
  h.releaseBody({id:1});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(form.resetCount, 0, 'An old task response must preserve the new session draft');
  assert.equal(h.run('token'), 'new-session');
  // Board lanes derive from ownership and agent reports, never from a visual move.
  const board=harness(200);
  for(const [state,expected] of [['working','working'],['blocked','blocked'],['local_done','review'],['pushed','review'],['pr_open','review'],['merged','merged']]) {
    assert.equal(board.run(`taskColumn({owner_member_id:1},{state:'${state}'})`),expected);
  }
  assert.equal(board.run('taskColumn({owner_member_id:null},{state:"merged"})'),'open');
  assert.equal(board.run('taskColumn({owner_member_id:1},null)'),'working');
  board.run(`const fixtureTasks=[{id:1,title:'Login',scope:'src/auth',intent_key:'login',owner_member_id:1},{id:2,title:'UI',scope:'src/web',intent_key:'ui',owner_member_id:2},{id:3,title:'Pending',scope:'src/new',intent_key:'new',owner_member_id:null}];
    const fixtureProgress=[{task_id:1,summary:'Waiting for token'}];`);
  assert.equal(board.run('matchingTasks(fixtureTasks,fixtureProgress,"TOKEN","1").length'),1);
  assert.equal(board.run('matchingTasks(fixtureTasks,fixtureProgress,"TOKEN","2").length'),0);
  assert.equal(board.run('matchingTasks(fixtureTasks,fixtureProgress,"","unassigned")[0].id'),3);
  assert.equal(board.run('matchingTasks(fixtureTasks,fixtureProgress,"SRC/WEB","")[0].id'),2);
  const card=board.element('focused-card');
  card.id='focused-card';card.tagName='BUTTON';card.textContent='task';card.tabIndex=0;
  card.focus=()=>{card.wasFocused=true;};card.querySelectorAll=()=>[];
  board.run('restoreRecordFocus({record:"focused-card",tag:"BUTTON",label:"task"})');
  assert.equal(card.wasFocused,true);
  assert.equal(card.tabIndex,0,'Refreshing a focused native card must retain its Tab stop');
  process.stdout.write('Delayed-body session regressions passed\n');
})().catch(error => { process.stderr.write(error.stack+'\n'); process.exitCode=1; });
