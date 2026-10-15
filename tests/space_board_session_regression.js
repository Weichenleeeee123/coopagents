'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[2]||'src/static/space_board.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function scenario(oldStatus){
  const elements=new Map(),listeners={},pending=[],streams=[],timers=new Map();let timerId=0;
  class Node {
    constructor(id){this.id=id;this.value='';this.children=[];this.textContent='';this.open=false;this.handlers={};}
    append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}
    addEventListener(event,fn){this.handlers[event]=fn;}focus(){}close(){this.open=false;this.handlers.close?.();}
  }
  const element=id=>{if(!elements.has(id))elements.set(id,new Node(id));return elements.get(id);};
  const location={origin:'http://127.0.0.1:8000',pathname:'/board',hash:'#first-ticket'};
  const context=vm.createContext({window:{CoopagentsBoard:{columns:[],matchingTasks:()=>[],request:()=>{},contract:()=>{}},CoopagentsRealtime:{connect:options=>{const stream={options,closed:false,close(){this.closed=true;}};streams.push(stream);return stream;}},addEventListener:(event,fn)=>listeners[event]=fn},
    document:{getElementById:element,createElement:tag=>new Node(tag),activeElement:null},location,
    history:{replaceState(){location.hash='';}},AbortController,Date,JSON,
    setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id),
    fetch:(path,options)=>new Promise(resolve=>pending.push({path,options,resolve}))});
  const response=(status,data)=>({status,ok:status===200,json:async()=>data});
  const snapshot=name=>({room:{name},members:[],tasks:[],progress:[],sessions:[],requests:[],contracts:[]});
  vm.runInContext(source,context);
  assert.equal(pending[0].path,'/board/session');assert.equal(location.hash,'');
  pending[0].resolve(response(200,{token:'first-session'}));await tick();
  const old=pending[1];assert.equal(old.options.headers.Authorization,'Bearer first-session');
  location.hash='#fresh-ticket';listeners.hashchange?.();await tick();
  assert.equal(location.hash,'','Fresh same-tab ticket must be removed from the address');
  assert.equal(pending[2]?.path,'/board/session','Fresh fragment must redeem a new session');
  assert.equal(JSON.parse(pending[2].options.body).ticket,'fresh-ticket');
  assert(old.options.signal.aborted,'Previous snapshot must be aborted');assert(streams[0].closed,'Previous event stream must close');
  pending[2].resolve(response(200,{token:'second-session'}));await tick();
  const current=pending[3];assert.equal(current.options.headers.Authorization,'Bearer second-session');
  current.resolve(response(200,snapshot('New session room')));await tick();
  assert.equal(element('room-name').textContent,'New session room');
  old.resolve(response(oldStatus,snapshot('Old session room')));await tick();
  streams[0].options.status('denied');await tick();
  assert.equal(element('room-name').textContent,'New session room','Old response must not replace the fresh session');
  assert.equal(element('board-error').textContent,'','Old 401/error must not invalidate the fresh session');
  assert(!streams[1].closed,'Stale denial must leave the new stream active');
  assert.equal([...timers.values()].filter(t=>t.delay===5000).length,1,'Only the fresh session owns a poll timer');
  listeners.pagehide();assert(streams[1].closed);assert.equal(timers.size,0);
}
(async()=>{await scenario(200);await scenario(401);console.log('Local board same-tab ticket recovery, aborted requests and stale responses passed');})().catch(error=>{console.error(error);process.exitCode=1;});
