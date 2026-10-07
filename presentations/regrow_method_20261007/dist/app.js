'use strict';
const $=s=>document.querySelector(s);
const deck=$('#deck');
deck.innerHTML=slides.map((s,i)=>`<section class="slide" id="slide-${i+1}" aria-label="第 ${i+1} 页：${s.title}"><div class="eyebrow">${s.eyebrow}</div>${s.hero?'':`<h2>${s.title}</h2><p class="subtitle">${s.subtitle}</p>`}<div class="${s.hero?'content hero-content':'content'}">${s.body}</div></section>`).join('');
$('#progress').innerHTML=slides.map((s,i)=>`<button data-goto="${i}" aria-label="第 ${i+1} 页：${s.title}"></button>`).join('');
$('#overviewItems').innerHTML=slides.map((s,i)=>`<button data-goto="${i}"><small>${String(i+1).padStart(2,'0')} / ${s.chapter}</small>${s.title}</button>`).join('');
let current=0;
function show(index,updateHash=true){
 current=Math.max(0,Math.min(slides.length-1,index));
 document.querySelectorAll('.slide').forEach((el,i)=>{el.classList.toggle('active',i===current);el.setAttribute('aria-hidden',String(i!==current));});
 document.querySelectorAll('#progress button').forEach((el,i)=>{el.classList.toggle('active',i===current);el.setAttribute('aria-current',i===current?'step':'false');});
 $('#chapter').textContent=slides[current].chapter+' / regrow';
 $('#page').textContent=String(current+1).padStart(2,'0')+' / '+slides.length;
 $('#prev').disabled=current===0;$('#next').disabled=current===slides.length-1;
 $('#noteBody').replaceChildren(); const p=document.createElement('p');p.textContent=slides[current].note;$('#noteBody').append(p);
 if(updateHash)history.replaceState(null,'','#'+(current+1));
 document.title=`${current+1} / ${slides.length} · ${slides[current].title} — regrow`;
 window.scrollTo({top:0,behavior:'instant'});
}
function fromHash(){const n=Number(location.hash.slice(1));show(Number.isInteger(n)&&n>0?n-1:0,false);}
$('#prev').onclick=()=>show(current-1);$('#next').onclick=()=>show(current+1);
document.querySelectorAll('[data-goto]').forEach(b=>b.onclick=()=>{show(Number(b.dataset.goto));$('#overview').close();});
$('#overviewBtn').onclick=()=>$('#overview').showModal();$('#closeOverview').onclick=()=>$('#overview').close();
function notesToggle(force){const open=force===undefined?$('#notes').hidden:force;$('#notes').hidden=!open;$('#notesBtn').setAttribute('aria-pressed',String(open));}
$('#notesBtn').onclick=()=>notesToggle();$('#closeNotes').onclick=()=>notesToggle(false);
function toast(t){$('#toast').textContent=t;$('#toast').style.display='block';setTimeout(()=>$('#toast').style.display='none',3500);}
async function fullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else if(document.documentElement.requestFullscreen)await document.documentElement.requestFullscreen();else toast('此浏览器不支持全屏，可使用浏览器的演示或全屏功能。');}catch{toast('无法进入全屏，可使用浏览器的全屏功能。');}}
$('#fullBtn').onclick=fullscreen;
document.querySelectorAll('[data-zoom]').forEach(img=>{
 img.tabIndex=0;img.setAttribute('role','button');img.setAttribute('aria-haspopup','dialog');
 const open=()=>{$('#largeImage').src=img.src;$('#largeImage').alt=img.alt;$('#largeCaption').textContent=img.closest('figure').querySelector('figcaption').textContent;$('#lightbox').showModal();};
 img.addEventListener('click',open);
 img.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();open();}});
});
$('#closeLightbox').onclick=()=>$('#lightbox').close();
const walkTexts=['添加入口揭示城市对话框。此时只证明入口去向，还不能说“城市已添加”。','搜索 London 后有多个国家的候选。查询文本与具体城市对象不能混为一谈。','选中英国 London 后，还需要提交添加。选中状态本身不代表完成。','实际点击 Add 后，世界时钟列表出现 London；用新观察核对这一结果。'];
document.querySelectorAll('[data-frame]').forEach(b=>b.onclick=()=>{const i=Number(b.dataset.frame),f=desktopFrames[i],figure=$('.walkthrough');figure.querySelector('img').src='assets/'+f.src;figure.querySelector('img').alt=f.caption;figure.querySelector('figcaption').textContent=f.caption;$('#walkText').textContent=walkTexts[i];document.querySelectorAll('[data-frame]').forEach(x=>{const selected=x===b;x.classList.toggle('selected',selected);x.setAttribute('aria-pressed',String(selected));});});
document.addEventListener('keydown',e=>{
 if(e.altKey||e.ctrlKey||e.metaKey||/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;
 if(document.querySelector('dialog[open]'))return;
 if(e.key==='Escape'){notesToggle(false);return;}
 if(['ArrowRight','PageDown'].includes(e.key)||(e.key===' '&&e.target.tagName!=='BUTTON')){e.preventDefault();show(current+1);}
 else if(['ArrowLeft','PageUp'].includes(e.key)){e.preventDefault();show(current-1);}
 else if(e.key==='Home'){e.preventDefault();show(0);}else if(e.key==='End'){e.preventDefault();show(slides.length-1);}
 else if(e.key.toLowerCase()==='o')$('#overview').showModal();else if(e.key.toLowerCase()==='n')notesToggle();else if(e.key.toLowerCase()==='f')fullscreen();
});
window.addEventListener('hashchange',fromHash);fromHash();
