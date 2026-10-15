'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let timers=[],sockets=[],refreshes=0,resolveRefresh;
class Socket {constructor(url){this.url=url;sockets.push(this);}send(frame){this.sent=JSON.parse(frame);}close(){this.closed=true;}message(data){this.onmessage({data:JSON.stringify(data)});}}
const context={window:{},WebSocket:Socket,URL,location:{origin:'http://127.0.0.1:8000'},setTimeout:fn=>{timers.push(fn);return fn;},clearTimeout:id=>{timers=timers.filter(t=>t!==id);},console};
vm.createContext(context);vm.runInContext(fs.readFileSync('src/static/realtime_client.js','utf8'),context);
async function tick(){await Promise.resolve();await Promise.resolve();await Promise.resolve();}
(async()=>{
 const states=[];
 const client=context.window.CoopagentsRealtime.connect({token:'private',refresh:()=>{refreshes++;return new Promise(resolve=>resolveRefresh=resolve);},status:s=>states.push(s)});
 const ws=sockets[0];ws.onopen();assert.equal(ws.sent.token,'private');assert.equal(ws.sent.after_id,0);
 ws.message({type:'ready',high_water:10});assert.equal(refreshes,1);
 ws.message({type:'events',cursor:11});ws.message({type:'events',cursor:12});assert.equal(refreshes,1);
 resolveRefresh();await tick();assert.equal(refreshes,2);resolveRefresh();await tick();
 ws.message({type:'reset',cursor:5});resolveRefresh();await tick();
 ws.onclose({code:1006});assert(states.includes('degraded'));timers.shift()();const newer=sockets[1];newer.onopen();assert.equal(newer.sent.after_id,5);
 client.close();const count=refreshes;ws.message({type:'events',cursor:99});assert.equal(refreshes,count);assert(newer.closed);
 const denied=context.window.CoopagentsRealtime.connect({token:'denied',refresh:()=>Promise.resolve(),status:()=>{}});sockets[2].onclose({code:4401});assert.equal(timers.length,0);denied.close();
 console.log('Realtime coalescing, cursor reset, reconnect and stale guards passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
