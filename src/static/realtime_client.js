'use strict';
(() => {
  function connect({token,refresh,status=()=>{},origin=location.origin}){
    let stopped=false,socket=null,retryTimer=null,cursor=0,delay=500,serial=0,busy=false,dirty=false;
    const valid=(ws,id)=>!stopped&&socket===ws&&serial===id;
    async function invalidate(){
      if(stopped)return;
      dirty=true;if(busy)return;busy=true;
      try{while(dirty&&!stopped){dirty=false;try{await refresh();}catch{if(!stopped)status('degraded');}}}
      finally{busy=false;}
    }
    function open(){
      if(stopped)return;
      const id=++serial,url=new URL('/api/events',origin);url.protocol=url.protocol==='https:'?'wss:':'ws:';
      let ws;
      try{ws=new WebSocket(url.href);socket=ws;}catch{status('degraded');retryTimer=setTimeout(open,delay);delay=Math.min(delay*2,15000);return;}
      ws.onopen=()=>{if(valid(ws,id))ws.send(JSON.stringify({token,after_id:cursor}));};
      ws.onmessage=event=>{
        if(!valid(ws,id))return;
        let frame;try{frame=JSON.parse(event.data);}catch{return;}
        if(frame.type==='ready'){delay=500;status('online');invalidate();}
        // Capture watermark before refreshing: later changes remain replayable.
        if(['events','reset'].includes(frame.type)&&Number.isSafeInteger(frame.cursor)&&frame.cursor>=0){cursor=frame.cursor;invalidate();}
      };
      ws.onerror=()=>{if(valid(ws,id))status('degraded');};
      ws.onclose=event=>{
        if(!valid(ws,id))return;socket=null;status(event.code===4401?'denied':'degraded');
        if(event.code===4401||event.code===4403||event.code===4400){stopped=true;return;}
        retryTimer=setTimeout(open,delay);delay=Math.min(delay*2,15000);
      };
    }
    open();
    return {close(){stopped=true;serial++;dirty=false;clearTimeout(retryTimer);socket?.close();socket=null;}};
  }
  window.CrewmeshRealtime={connect};
})();
