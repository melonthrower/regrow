/* Workspace notes. Each recovery snapshot has its own immutable browser key. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  let state=null,prefix=null,ownKey=null,adopted=null,dirty=false,generation=0,timer=null,saving=null,locked=false,recovery=null;
  const status=(text,error=false)=>{$('worklog-status').textContent=text;$('worklog-status').className=error?'error':'';};
  const syncLock=()=>{for(const id of ['worklog','save-worklog'])$(id).disabled=locked||!state||!!recovery;for(const id of ['use-recovered-worklog','keep-server-worklog','worklog-drafts'])$(id).disabled=locked;};
  function removeKey(key){if(key)try{localStorage.removeItem(key);}catch(error){}}
  function backup(){
    if(!prefix||!state)return;
    try{
      const key=prefix+crypto.randomUUID();
      localStorage.setItem(key,JSON.stringify({text:$('worklog').value,version:state.version,time:Date.now()}));
      removeKey(ownKey);ownKey=key;
    }catch(error){status('浏览器恢复副本未能写入，正在尝试保存到服务器。',true);}
  }
  function clearSaved(){removeKey(ownKey);ownKey=null;if(adopted){removeKey(adopted.key);adopted=null;}}
  function drafts(){
    const found=[];
    try{
      for(let i=0;i<localStorage.length;i++){
        const key=localStorage.key(i);if(!key.startsWith(prefix))continue;
        try{const value=JSON.parse(localStorage.getItem(key));if(typeof value.text==='string')found.push({...value,key});}catch(error){}
      }
    }catch(error){}
    for(const item of found)if(item.text===state.text)removeKey(item.key);
    return found.filter(item=>item.text!==state.text).sort((a,b)=>(b.time||0)-(a.time||0));
  }
  async function request(body,keepalive=false){
    const response=await fetch('/api/editor/worklog',body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),keepalive}:{});
    const result=await response.json();if(!response.ok){const error=new Error(result.error||'工作记录保存失败。');error.status=response.status;throw error;}return result;
  }
  function showRecovery(items){
    // Recovery entries are independent snapshots, no longer this page's replaceable active draft.
    ownKey=null;
    recovery=items[0];$('worklog').value=state.text;$('worklog-drafts').replaceChildren();
    for(const item of items){const option=document.createElement('option');option.value=item.key;option.textContent=(item.time?new Date(item.time).toLocaleString():'恢复稿')+' · '+item.text.slice(0,35);option._draft=item;$('worklog-drafts').append(option);}
    $('recovered-worklog').value=recovery.text;$('worklog-recovery').hidden=false;dirty=false;syncLock();
    status('找到未保存的恢复稿，未覆盖服务器记录；请在下方选择。',true);
  }
  function changed(){dirty=true;generation++;backup();$('submission').hidden=true;status('工作记录待保存…');clearTimeout(timer);timer=setTimeout(save,650);}
  const ready=(async()=>{
    try{
      state=await request();prefix='regrow-prompt-worklog:'+state.workspace+':';$('worklog').value=state.text;syncLock();
      const pending=drafts();
      if(pending.length===1&&pending[0].version===state.version){adopted=pending[0];$('worklog').value=adopted.text;changed();status('已恢复未保存草稿，正在保存…');}
      else if(pending.length)showRecovery(pending);
      else status(state.saved_at?'已恢复项目中的工作记录':'可以在这里记录总体思路');
    }catch(error){status('工作记录读取失败：'+error.message,true);}
  })();
  async function save(){
    await ready;clearTimeout(timer);
    if(!state||recovery)return false;
    if(saving){const ok=await saving;return ok&&dirty?save():ok;}
    if(!dirty)return true;
    const sent=generation,payload={version:state.version,text:$('worklog').value};status('正在保存工作记录…');
    saving=(async()=>{
      try{
        state=await request(payload);if(sent===generation){dirty=false;clearSaved();}else backup();
        status(dirty?'还有工作记录待保存…':'工作记录已保存到项目目录');return true;
      }catch(error){
        backup();
        if(error.status===409){
          try{const server=await request();backup();state=server;const pending=drafts();if(pending.length)showRecovery(pending);else{dirty=false;clearSaved();$('worklog').value=state.text;status('工作记录已保存到项目目录');}return !recovery;}catch(readError){}
        }
        status(error.message+' 恢复副本仍保留在本浏览器。',true);return false;
      }
    })();
    const ok=await saving;saving=null;if(ok&&dirty)return save();return ok;
  }
  function flushOnLeave(){
    if(!state||!dirty||recovery)return;
    backup();
    try{fetch('/api/editor/worklog',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:state.version,text:$('worklog').value}),keepalive:true}).catch(()=>{});}catch(error){}
  }
  $('worklog').addEventListener('input',changed);$('save-worklog').addEventListener('click',save);
  $('worklog-drafts').addEventListener('change',()=>{recovery=$('worklog-drafts').selectedOptions[0]._draft;$('recovered-worklog').value=recovery.text;});
  $('use-recovered-worklog').addEventListener('click',()=>{adopted=recovery;const text=recovery.text;recovery=null;$('worklog-recovery').hidden=true;$('worklog').value=text;syncLock();changed();});
  $('keep-server-worklog').addEventListener('click',()=>{removeKey(recovery.key);if(ownKey===recovery.key)ownKey=null;recovery=null;const pending=drafts();if(pending.length)showRecovery(pending);else{$('worklog-recovery').hidden=true;syncLock();status('已保留服务器中的工作记录');}});
  window.addEventListener('pagehide',flushOnLeave);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')flushOnLeave();});
  window.promptWorklog={save,lock(value){locked=value;syncLock();},ready};
})();
