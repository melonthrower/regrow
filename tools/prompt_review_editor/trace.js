(() => {
'use strict';
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const api=async(path,body)=>{const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const v=await r.json();if(!r.ok)throw Error(v.error||'读取失败');return v;};
const pretty=x=>typeof x==='string'?x:JSON.stringify(x,null,2);
const box=(title,value,open=false)=>{const d=el('details');d.open=open;d.append(el('summary',title),el('pre',pretty(value)??'未保存'));return d;};
const panel=el('section',undefined,'trace-panel');panel.id='trace-panel';
const title=el('h2','代表性案例'),select=el('select'),steps=el('nav',undefined,'trace-steps'),status=el('p','正在读取轨迹…','note'),body=el('div'),jobsBox=el('details');jobsBox.append(el('summary','已保存的预览与测试'));
panel.append(title,select,steps,status,body,jobsBox);const main=document.querySelector('main');main.insertBefore(panel,main.querySelector('nav')||main.firstChild);
window.traceShowJob=(id,out)=>watch(id,out);
window.addEventListener('working-request-updated',()=>{if(current)loadStep(current.call);});
let catalog=[],chosen=null,current=null,generation=0;
const setStatus=t=>status.textContent=t;
function requestView(parent,q,label,open=false){
 const d=el('details');d.open=open;d.append(el('summary',label));
 d.append(box('System · 完整正文',q.system_prompt,true),box('User · 任务与上下文历史（完整正文）',q.user_prompt,true),box('输出结构',q.response_schema));parent.append(d);
}
function currentDraftView(draft,item){
 const currentDraft=el('section');currentDraft.id='current-draft';
 currentDraft.append(el('h3','当前稿'));
 if(draft.preview){
  const task=draft.preview.work_context?.task;currentDraft.append(el('p','探索任务：'+(task?.name||draft.preview.source?.task_name||'本步没有指定控件任务')));
  requestView(currentDraft,draft.preview,'当前工作版本 · 完整请求',true);
  currentDraft.append(el('p','来自已保存工作版本 '+draft.revision+'；未收录的其他讨论稿不自动混入。','note'));
 }else{
  currentDraft.append(el('p',draft.dirty_modules.length?'模块又有修改，下面展示最新模块稿；保存本轮版本并预览后可查看完整请求。':'当前版本尚未生成这一步的完整请求。下面是最新模块稿，不冒充拼接后的请求。','note'));
  for(const part of draft.modules)currentDraft.append(box(part.path,part.text,true));
 }
 return currentDraft;
}
async function refreshCurrentDraft(){
 if(!current||!chosen)return;const item=current,key=chosen.id;try{const draft=await api('/api/trace/current?trace='+encodeURIComponent(key)+'&call='+item.call);if(current===item&&chosen.id===key)document.getElementById('current-draft')?.replaceWith(currentDraftView(draft,item));}catch(e){setStatus(e.message);}
}
window.addEventListener('focus',refreshCurrentDraft);window.addEventListener('prompt-draft-saved',refreshCurrentDraft);window.addEventListener('storage',event=>{if(event.key==='regrow-prompt-change')refreshCurrentDraft();});
async function loadStep(call){
 const turn=++generation;setStatus('读取 '+call+'…');
 try{
 const key=chosen.id;const [item,draft]=await Promise.all([api('/api/trace/step?trace='+encodeURIComponent(key)+'&call='+call),api('/api/trace/current?trace='+encodeURIComponent(key)+'&call='+call)]);if(turn!==generation)return;current=item;body.replaceChildren();
 for(const b of steps.children)b.setAttribute('aria-current',b.dataset.call===call?'step':'false');
 const heading=el('h3',call+' · '+item.label);body.append(heading);
 const images=el('div',undefined,'trace-images');(item.request.screenshots||[]).forEach((_,i)=>{const f=el('figure'),img=el('img');img.src='/api/trace/image?trace='+encodeURIComponent(chosen.id)+'&call='+call+'&index='+i;img.alt='调用 '+call+' 的原始截图 '+(i+1);f.append(img,el('figcaption','原始截图 '+(i+1)+' · 历史保存帧'));images.append(f);});body.append(images);
 body.append(currentDraftView(draft,item));
 const historical=el('details');historical.id='historical-call';historical.append(el('summary','历史原文与执行记录（仅供对照）'));
 historical.append(box('内部调度与调用来源',item.request.work_context||item.request.source||item.request.discovery_context));
 requestView(historical,item.request,'当时实际发送的请求');
 historical.append(box('调用前登记的区块、控件与状态',item.before),box('Luna 原答',item.response),box('校验、纠错与结算记录',item.repairs),box('实际动作与回执',item.actions),box('本次正式登记',item.after),box('用量与错误',{usage:item.usage,error:item.error}));body.append(historical);
 const edit=el('details');edit.open=false;edit.append(el('summary','当前稿预览与保存帧测试'),el('p','勾选要试的模块；未勾选部分使用当前框架源码。预览不调用 Luna；测试最多 3 次调用，包含纠错，不执行 GUI。','note'));
 const choices=el('div');
 for(const name of item.modules){const row=el('div'),check=el('input');check.type='checkbox';check.value=name;const label=el('label');label.append(check,document.createTextNode(name+' '));const link=el('a','编辑');link.href='/editor?path='+encodeURIComponent(name);link.target='_blank';const locate=el('button','查看本次引用');locate.onclick=()=>{const old=row.querySelector('pre');if(old)old.remove();else row.append(el('pre',item.request.fixed_parts.filter(p=>p.path.split('/片段-',1)[0]===name).map(p=>p.text).join('\n\n')));};row.append(label,link,locate);choices.append(row);}edit.append(choices);
 const preview=el('button','预览修改后的请求'),test=el('button','用保存帧测试'),out=el('div');
 preview.disabled=test.disabled=!item.replayable;edit.append(el('p',item.replay_note,'note'),preview,test,out);body.append(edit);
 async function start(mode){preview.disabled=test.disabled=true;setStatus(mode==='preview'?'正在正常组装请求…':'正在保存帧测试…');try{const job=await api('/api/trace/start',{trace:chosen.id,call,mode,modules:[...choices.querySelectorAll('input:checked')].map(n=>n.value)});await watch(job.id,out);}catch(e){setStatus(e.message);}finally{preview.disabled=test.disabled=!item.replayable;}}
 preview.onclick=()=>start('preview');test.onclick=()=>start('test');
 window.dispatchEvent(new CustomEvent('trace-step-selected',{detail:{trace:chosen.id,call,item}}));
 setStatus('默认查看当前稿；历史全文在下方折叠对照。');const url=new URL(location.href);url.searchParams.set('trace_call',call);url.searchParams.set('trace',chosen.id);history.replaceState(null,'',url);
 }catch(e){setStatus(e.message);}
}
function drawJob(job,out){out.replaceChildren(el('h3','结果：'+job.status),el('p',`调用 ${job.calls||0} 次 · GUI 0 次 · ${job.id}`));if(job.error)out.append(el('p',job.error,'error'));if(job.preview)requestView(out,job.preview,'当前代码与所选稿组装的完整请求');if(job.summary)out.append(box('历史原件与当前重建的差异（包含后续框架改动）',job.summary,true));if(job.result)out.append(box('正常校验与登记结果',job.result,true));if(job.calls_detail?.length)out.append(box('本次所有调用、原答、纠错与用量',job.calls_detail));if(job.reused_frames?.length)out.append(box('纠错补观察复用的保存帧（没有新GUI）',job.reused_frames));if(job.after)out.append(box('登记后的对象与任务',job.after));if(job.images?.length){const gallery=el('details');gallery.append(el('summary','登记中的识别用截图（含沿用旧图）'));const images=el('div',undefined,'trace-images');for(const item of job.images){const f=el('figure'),img=el('img');img.loading='lazy';img.src='/api/trace/job-image?id='+encodeURIComponent(job.id)+'&index='+item.index;img.alt=item.name;f.append(img,el('figcaption',item.name));images.append(f);}gallery.append(images);out.append(gallery);}if(job.next_request)out.append(box('下一步读取',job.next_request));out.append(el('p','保存帧结果需要语义检查；动作选择未执行，不使用旧后图证明新动作成功。','note'));
 if(job.writeback?.paths?.length){
  const section=el('section');section.append(el('h4','写回此版本'),el('p',job.writeback.paths.join('、')),el('p',job.writeback.reason,'note'));
  const apply=el('button','将此版本写回本地源码');apply.disabled=!job.writeback.ready;
  apply.onclick=async()=>{apply.disabled=true;try{const result=await api('/api/trace/apply',{id:job.id});section.append(el('p',result.note));setStatus('已写回 '+result.paths.length+' 份稿件，旧版已备份');}catch(error){section.append(el('p',error.message,'error'));}};
  section.append(apply);out.append(section);
 }
}
async function watch(id,out){while(true){const job=await api('/api/trace/job?id='+encodeURIComponent(id));drawJob(job,out);if(job.status!=='running'){setStatus('已保存：'+job.status);await refreshJobs();break;}await new Promise(r=>setTimeout(r,1500));}}
async function refreshJobs(){const data=await api('/api/trace');jobsBox.replaceChildren(el('summary','已保存的预览与测试'));for(const j of data.jobs){const b=el('button',`${j.call} · ${j.mode} · ${j.status}`),out=el('div');b.onclick=()=>watch(j.id,out).catch(e=>setStatus(e.message));jobsBox.append(b,out);}}
function choose(){chosen=catalog.find(t=>t.id===select.value);document.querySelectorAll('.trace-refs').forEach(n=>n.remove());steps.replaceChildren();for(const s of chosen.steps){const b=el('button',s.call+' '+s.label);b.dataset.call=s.call;b.onclick=()=>loadStep(s.call);steps.append(b);}const params=new URLSearchParams(location.search);const requested=params.get('trace_call');loadStep(chosen.steps.some(s=>s.call===requested)?requested:chosen.steps[0].call);addReferences();window.dispatchEvent(new CustomEvent('prompt-document-loaded',{detail:document.getElementById('document')?.value}));}
function addReferences(){
 document.querySelectorAll('a.edit-link').forEach(link=>{if(link.nextElementSibling?.classList.contains('trace-refs'))return;const name=new URL(link.href).searchParams.get('path');const refs=el('span',undefined,'trace-refs');refs.append(document.createTextNode(' 轨迹引用：'));const used=chosen.steps.filter(s=>s.modules.includes(name));for(const s of used){const b=el('button',s.call);b.onclick=()=>{loadStep(s.call);panel.scrollIntoView();};refs.append(b);}if(!used.length)refs.append(document.createTextNode('此轨迹未引用'));link.after(refs);});
}
window.addEventListener('prompt-document-loaded',event=>{if(!chosen)return;document.getElementById('editor-trace-refs')?.remove();const refs=el('p',undefined,'note');refs.id='editor-trace-refs';refs.append(document.createTextNode('此模块用于：'));for(const s of chosen.steps.filter(s=>s.modules.includes(event.detail))){const b=el('button',s.call+' '+s.label);b.onclick=()=>{loadStep(s.call);panel.scrollIntoView();};refs.append(b);}document.getElementById('status')?.after(refs);});
api('/api/trace').then(data=>{catalog=data.traces;if(!catalog.length){setStatus('尚未载入真实轨迹');return;}for(const archived of [false,true]){const group=el('optgroup');group.label=archived?'原始记录':'调试案例';for(const t of catalog.filter(t=>Boolean(t.archived)===archived)){const option=el('option',t.title);option.value=t.id;group.append(option);}select.append(group);}const saved=new URLSearchParams(location.search).get('trace');if(catalog.some(t=>t.id===saved))select.value=saved;select.onchange=choose;choose();refreshJobs();const content=document.getElementById('content');if(content)new MutationObserver(addReferences).observe(content,{childList:true});}).catch(e=>setStatus(e.message));
})();
