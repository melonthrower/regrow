(() => {
'use strict';
const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
const api=async(path,value)=>{const r=await fetch(path,value?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)}:{});const v=await r.json();if(!r.ok)throw Error(v.error||'操作未完成');return v;};
let selection=null,work=null,epoch=0;
const draftKey=()=> 'regrow-working-context:'+selection.trace+':'+selection.call;
const panel=el('details');panel.id='working-trace';const message=el('p');message.setAttribute('role','status');
async function refresh(){const ticket=++epoch;if(!selection)return;const result=await api('/api/trace/work?trace='+encodeURIComponent(selection.trace));if(ticket!==epoch)return;work=result;render();}
function render(){
 panel.replaceChildren(el('summary','修改与测试'),message);
 const key=selection.trace,call=selection.call,contextKey=draftKey();
 const rev=work.revision;message.textContent=rev.id?'当前版本：'+rev.id:'尚未保存工作版本；选好模块后统一保存，不会调用 Luna。';
 if(work.unsaved_modules.length)message.textContent+=' · 有 '+work.unsaved_modules.length+' 个模块修改尚未收录';
 const mods=el('details');mods.append(el('summary','本轮要修改的模块'));const names=[...new Set(work.steps.flatMap(s=>s.modules))];
 for(const name of names){const label=el('label'),check=el('input');check.type='checkbox';check.value=name;check.checked=Object.hasOwn(rev.modules,name);label.append(check,document.createTextNode(' '+name+' '));const link=el('a','编辑');link.href='/editor?path='+encodeURIComponent(name);link.target='_blank';const row=el('div');row.append(label,link);mods.append(row);}panel.append(mods);
 const stepChoices=el('div');stepChoices.className='work-step-choices';
 for(const s of work.steps){const label=el('label'),check=el('input');check.type='checkbox';check.value=s.call;check.checked=s.affected;check.disabled=s.role==='step_correction';label.append(check,document.createTextNode(` ${s.call} ${s.label}${s.affected?' · 受影响':''}${s.context_edited?' · 案例上下文已改':''}${s.stale?' · 上下文待更新':''}`));stepChoices.append(label,el('br'));}panel.append(stepChoices);
 const context=el('details');context.append(el('summary','编辑本步案例上下文'));
 context.append(el('p','修改底层任务、区块、控件或历史记录，再由框架生成请求。原始记录不变；这种测试会标为编辑案例，不作为未修改真实记录的验收。截图来源保持原样。'));
 const source=rev.contexts[call]||selection.item.before;const area=el('textarea');area.rows=12;area.value=localStorage.getItem(contextKey)||JSON.stringify(source,null,2);area.disabled=!source;area.oninput=()=>{localStorage.setItem(contextKey,area.value);saveContext.checked=true;};context.append(area);
 const saveContext=el('input');saveContext.type='checkbox';saveContext.disabled=!source;saveContext.checked=localStorage.getItem(contextKey)!==null;const use=el('label');use.append(saveContext,document.createTextNode('将这份上下文收入本轮版本'));context.append(use);panel.append(context);
 const save=el('button','保存本轮版本'),preview=el('button','批量预览'),test=el('button','统一测试'),reload=el('button','检查模块改动');preview.disabled=test.disabled=!rev.id;
 const out=el('div');panel.append(save,preview,test,reload,out);
 save.onclick=async()=>{try{const contexts=saveContext.checked?{[call]:JSON.parse(area.value)}:{};await api('/api/trace/work-save',{trace:key,parent:rev.id,modules:[...mods.querySelectorAll('input:checked')].map(x=>x.value),contexts});localStorage.removeItem(contextKey);await refresh();window.dispatchEvent(new Event('working-request-updated'));message.textContent+=' · 已保存，未调用模型';}catch(e){message.textContent=e.message;}};
 reload.onclick=()=>refresh().then(()=>window.dispatchEvent(new Event('prompt-draft-saved'))).catch(e=>message.textContent=e.message);
 async function launch(mode){try{if(JSON.stringify([...mods.querySelectorAll('input:checked')].map(x=>x.value).sort())!==JSON.stringify(Object.keys(rev.modules).sort()))throw Error('模块选择已变化，请先保存本轮版本');if(saveContext.checked)throw Error('先保存本步上下文');const calls=[...stepChoices.querySelectorAll('input:checked')].map(x=>x.value);if(!calls.length)throw Error('请选择要预览或测试的步骤');preview.disabled=test.disabled=true;const b=await api('/api/trace/batch-start',{trace:key,revision:rev.id,mode,calls});await watch(b.id,key,out);}catch(e){message.textContent=e.message;}finally{preview.disabled=test.disabled=false;}}
 preview.onclick=()=>launch('preview');test.onclick=()=>launch('test');
 panel.append(el('p','预览不调用 Luna。统一测试按勾选步骤顺序执行，每步最多 3 次调用含纠错；遇到新动作或登记变化，后续标为待更新。'));
 const history=el('details');history.append(el('summary','版本与批次记录'));
 for(const v of work.versions)history.append(el('p',v.id+' · 模块 '+v.modules.length+' · 编辑上下文 '+v.contexts.length));
 for(const b of work.batches){const button=el('button',b.mode+' · '+b.status+' · '+b.id),result=el('div');button.onclick=()=>watch(b.id,key,result).catch(e=>message.textContent=e.message);history.append(button,result);}panel.append(history);
}
async function watch(id,key,out){
 const caseWork=await api('/api/trace/work?trace='+encodeURIComponent(key));
 while(true){const b=await api('/api/trace/batch?trace='+encodeURIComponent(key)+'&id='+id);out.replaceChildren(el('h4',`${b.mode} · ${b.status} · 调用 ${b.calls} 次`));
 for(const row of b.steps){const line=el('div');line.append(el('p',row.call+' · '+row.status+(row.reason?'：'+row.reason:'')+(row.downstream?'；'+row.downstream:'')));
 if(row.job){const show=el('button','查看完整请求与结果'),result=el('div');show.onclick=()=>window.traceShowJob(row.job,result);line.append(show,result);
 if(row.status==='checked'&&caseWork.steps.find(s=>s.call===row.call)?.role!=='action_selection'){const next=caseWork.steps[caseWork.steps.findIndex(s=>s.call===row.call)+1];if(next){const adopt=el('button','采用登记，更新 '+next.call+' 的上下文');adopt.onclick=async()=>{try{await api('/api/trace/adopt',{trace:key,call:next.call,job:row.job});await refresh();window.dispatchEvent(new Event('prompt-draft-saved'));message.textContent+=' · 已采用登记，请重新预览后续步骤';}catch(e){message.textContent=e.message;}};line.append(adopt);}}}
 out.append(line);}
 if(b.error)out.append(el('p',b.error));if(b.status!=='running'){const show=el('button','查看当前稿');show.onclick=()=>window.dispatchEvent(new Event('working-request-updated'));out.append(show);break;}await new Promise(r=>setTimeout(r,1000));}
}
window.addEventListener('trace-step-selected',event=>{selection=event.detail;const target=document.querySelector('.trace-steps');target.after(panel);refresh().catch(e=>message.textContent=e.message);});

})();
