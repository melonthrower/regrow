(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  let documentState=null, dirty=false, timer=null, saving=null, generation=0, notes=[], busy=false, reviewContext=new URLSearchParams(location.search).get('context');
  const status=(message,error=false)=>{$('status').textContent=message;$('status').className=error?'error':'';};
  function lock(value){
    for(const id of ['document','draft','idea','save','submit','clear-review-context'])$(id).disabled=value;
    $('annotate').disabled=value||$('draft').selectionStart===$('draft').selectionEnd;
    for(const el of $('notes').querySelectorAll('textarea,button'))el.disabled=value;
    window.promptWorklog.lock(value);
  }
  const json=async(url,body)=>{
    const response=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'保存未完成。');return result;
  };
  function changed(){dirty=true;generation++;$('submission').hidden=true;status('尚未保存…');clearTimeout(timer);timer=setTimeout(save,650);}
  const lineLabel=x=>x.end_line<x.start_line?`第 ${x.start_line} 行前`:`第 ${x.start_line}${x.end_line===x.start_line?'':`–${x.end_line}`} 行`;
  function showChanges(rows){
    $('changes').replaceChildren();
    if(!rows.length){$('changes').textContent='正文暂未修改；你仍可以写想法并准备审查。';return;}
    for(const row of rows){
      const box=document.createElement('div');box.className='change';
      const label=document.createElement('p');label.textContent=`${row.section||'正文'} · 改前 ${lineLabel(row.before)} → 改后 ${lineLabel(row.after)}`;
      const a=document.createElement('pre'),b=document.createElement('pre');a.className='removed';b.className='added';a.textContent=row.before.text||'（此处原本无文字）';b.textContent=row.after.text||'（已删除）';box.append(label,a,b);$('changes').append(box);
    }
  }
  function showNotes(focusId){
    $('notes').replaceChildren();
    for(const note of notes){
      const box=document.createElement('div');box.className='annotation';
      const label=document.createElement('label');label.htmlFor='note-'+note.id;label.textContent=`对标注时第 ${note.start_line}–${note.end_line} 行的想法`;
      const quote=document.createElement('blockquote');quote.textContent=note.quote;
      const field=document.createElement('textarea');field.id=label.htmlFor;field.rows=3;field.value=note.body;
      field.addEventListener('input',()=>{note.body=field.value;changed();});
      const remove=document.createElement('button');remove.textContent='移除这条说明';remove.addEventListener('click',()=>{notes=notes.filter(x=>x.id!==note.id);showNotes();changed();});
      box.append(label,quote,field,remove);$('notes').append(box);if(note.id===focusId)field.focus();
    }
  }
  async function save(){
    clearTimeout(timer);
    if(saving){const ok=await saving;return ok&&dirty?save():ok;}
    if(!dirty||!documentState)return true;
    const sent=generation,payload={path:documentState.path,version:documentState.version,text:$('draft').value,idea:$('idea').value,notes:JSON.parse(JSON.stringify(notes))};
    status('正在保存…');
    saving=(async()=>{
      try{
        const result=await json('/api/editor/save',payload);documentState.version=result.version;documentState.saved_at=result.saved_at;
        if(sent===generation)dirty=false;
        showChanges(result.changes);status(dirty?'还有新输入待保存…':'已保存到服务器');return true;
      }catch(error){status(error.message+' 未保存的文字仍在右侧，请勿关闭页面。',true);return false;}
    })();
    const ok=await saving;saving=null;if(ok&&dirty)return save();return ok;
  }
  async function load(path){
    const result=await json('/api/editor'+(path?'?path='+encodeURIComponent(path):''));
    documentState=result.document;notes=JSON.parse(JSON.stringify(documentState.notes));dirty=false;generation++;
    if(!$('document').options.length){
      const group=document.createElement('optgroup');group.label='提示正文';
      for(const name of result.paths){const option=document.createElement('option');option.value=name;option.textContent=name.replace(/\.prompt$/,'');group.append(option);}$('document').append(group);
      if(result.contexts?.length){const contexts=document.createElement('optgroup');contexts.label='上下文与历史（真实请求）';for(const item of result.contexts){const option=document.createElement('option');option.value='context:'+item.id;option.textContent=item.title;contexts.append(option);}$('document').append(contexts);}
    }
    $('document').value=documentState.path;$('base').textContent=documentState.base;$('draft').value=documentState.text;$('idea').value=documentState.idea;
    showNotes();showChanges(documentState.changes);$('annotate').disabled=true;
    const contextual=documentState.kind==='context';$('context-details').hidden=!contextual;
    $('context-images').replaceChildren();$('related-prompts').replaceChildren();
    if(contextual){
      const item=documentState.case;$('context-title').textContent=item.title;$('context-origin').textContent=`保存的调用 ${item.call} · ${item.images.length} 张原始附图`;$('context-system').textContent=documentState.system_prompt;
      reviewContext=item.id;$('review-context').hidden=false;$('review-context-label').textContent='本次审查附带历史：'+item.title;$('submission').hidden=true;
      item.images.forEach((frame,index)=>{const figure=document.createElement('figure'),img=document.createElement('img'),caption=document.createElement('figcaption');img.src='/api/editor/context-image?id='+encodeURIComponent(item.id)+'&index='+index;img.alt='该请求保存的附图 '+(index+1);caption.textContent='原始请求附图 '+(index+1)+'（复用保存帧）';figure.append(img,caption);$('context-images').append(figure);});
      $('related-prompts').append('同页关联的提示候选：');for(const name of item.related_prompts){const link=document.createElement('a');link.href='/editor?path='+encodeURIComponent(name)+'&context='+encodeURIComponent(item.id);link.target='_blank';link.rel='noopener';link.textContent=name.replace(/\.prompt$/,'');$('related-prompts').append(link,' ');}
    }
    const attached=(result.contexts||[]).find(item=>item.id===reviewContext);if(attached){$('review-context').hidden=false;$('review-context-label').textContent='本次审查附带历史：'+attached.title;}else{reviewContext=null;$('review-context').hidden=true;}
    for(const id of ['document','draft','idea','save','submit'])$(id).disabled=false;
    status(documentState.saved_at?'已读取保存的修改和想法':'可以开始编辑');
    const url=new URL(location.href);url.searchParams.set('path',documentState.path);if(reviewContext)url.searchParams.set('context',reviewContext);else url.searchParams.delete('context');history.replaceState(null,'',url);
  }
  $('draft').addEventListener('input',changed);$('idea').addEventListener('input',changed);
  $('draft').addEventListener('select',()=>{$('annotate').disabled=$('draft').selectionStart===$('draft').selectionEnd;});
  $('annotate').addEventListener('click',()=>{
    const text=$('draft').value,a=$('draft').selectionStart,b=$('draft').selectionEnd;if(a===b)return;
    const note={id:crypto.randomUUID(),body:'',quote:text.slice(a,b),source_text:text,
      start_line:text.slice(0,a).split('\n').length,end_line:text.slice(0,b-1).split('\n').length};
    notes.push(note);showNotes(note.id);changed();
  });
  $('save').addEventListener('click',save);
  $('clear-review-context').addEventListener('click',()=>{reviewContext=null;$('review-context').hidden=true;$('submission').hidden=true;const url=new URL(location.href);url.searchParams.delete('context');history.replaceState(null,'',url);});
  $('document').addEventListener('change',async()=>{
    if(busy)return;busy=true;const next=$('document').value;lock(true);
    try{if(await save())await load(next);else $('document').value=documentState.path;}
    catch(error){status(error.message,true);$('document').value=documentState.path;}
    finally{busy=false;lock(false);}
  });
  $('submit').addEventListener('click',async()=>{
    if(busy)return;busy=true;lock(true);
    try{
      if(!await save()||!await window.promptWorklog.save())return;
      const result=await json('/api/editor/submit',{contexts:reviewContext?[reviewContext]:[]});$('review-request').value=result.request;$('submission').hidden=false;
      $('submission').scrollIntoView({block:'nearest'});status(`已固定 ${result.count} 份材料修改和想法${result.has_worklog?'，并包含工作记录':''}。请将审查请求发回对话。`);
    }catch(error){status(error.message,true);}finally{busy=false;lock(false);}
  });
  $('copy-request').addEventListener('click',async()=>{
    try{await navigator.clipboard.writeText($('review-request').value);$('copy-status').textContent='已复制，请粘贴到对话。';}
    catch(error){$('review-request').focus();$('review-request').select();$('copy-status').textContent='请复制已选中的文字并发回对话。';}
  });
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  load(new URLSearchParams(location.search).get('path')).catch(error=>status('读取失败：'+error.message,true));
})();
