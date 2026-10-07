'use strict';
const $=s=>document.querySelector(s);
const starts=[];let total=0;SCENES.forEach(s=>{starts.push(total);total+=s.duration;});
let time=0,playing=false,rate=1,last=0,sceneIndex=-1,beatIndex=-1;
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
const smooth=v=>{v=clamp(v);return v*v*(3-2*v);};
const format=t=>String(Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t%60)).padStart(2,'0');
const picture=(asset,where={})=>{const [w,h]=ASSET_SIZES[asset];const maxW=where.w||900,maxH=where.h||450,k=Math.min(maxW/w,maxH/h);return `<div class="screenshot" style="width:${w*k}px;height:${h*k}px"><img src="film/assets/${asset}" alt="${SCENES[sceneIndex]?.app||'GNOME 官方界面截图'}"><svg viewBox="0 0 ${w} ${h}" aria-hidden="true"></svg></div>`;};
const side=s=>`<div class="right-panel"><div class="panel-label">框架在这一步做什么</div>${s.beats.map((b,i)=>`<div class="beat" data-beat="${i}"><span class="count">0${i+1}</span><b>${b[0]}</b><p>${b[1]}</p></div>`).join('')}</div>`;
const cursor='<svg class="cursor" viewBox="0 0 30 39" aria-hidden="true"><path d="M3 2 L3 31 L11 25 L17 37 L23 34 L17 22 L28 20 Z" fill="#fffef5" stroke="#272f23" stroke-width="2"/></svg>';
function mainVisual(s){
 if(s.kind==='intro')return `<div class="hero-title">先认识应用，<br>再构造<em>有意义</em>的轨迹。</div><div class="hero-sub">用视觉观察积累功能知识，<br>让任务生成与实时执行有据可依。</div><div class="montage"><img data-appear="0" src="film/assets/calendar.png" alt="官方日历素材"><img data-appear="1" src="film/assets/appearance.png" alt="官方设置素材"><img data-appear="2" src="film/assets/files.png" alt="官方文件管理器素材"></div><div class="intro-stages"><span>视觉探索</span><i>→</i><span>功能知识</span><i>→</i><span>目标与轨迹</span></div>`;
 if(s.kind==='compare')return `<div class="compare-images">${[s.asset,s.second].map((a,i)=>`<div class="compare-one" data-appear="${i}"><img src="film/assets/${a}" alt="${i?'声音':'外观'}设置官方素材"><div class="reuse-box"></div><b>${i?'不同内容：继续探索':'稳定部分：候选复用'}</b><small>独立官方素材，非动作前后对</small></div>`).join('')}</div><div class="same-link" data-appear="2">共享候选 → 当前核对 → 按来源复用</div>${side(s)}`;
 if(s.kind==='knowledge')return `<div class="visual" style="width:310px;left:71px">${picture(s.asset,{w:295,h:466})}</div><div class="knowledge-card" data-appear="1"><small>FUNCTION CARD · 结构示意</small><h3>修改一个日历事件</h3><div class="knowledge-row"><b>对象</b><span>当前选定的事件</span></div><div class="knowledge-row"><b>参数</b><span>标题、日期、时间、重复、提醒</span></div><div class="knowledge-row"><b>效果</b><span>需要保存后观察确认</span></div><div class="knowledge-row"><b>依据</b><span>支持任务与实际反馈；缺口保留</span></div></div>${side(s)}`;
 if(s.kind==='graph')return `<div class="graph-area"><svg viewBox="0 0 860 417"><path class="graph-line" d="M195 65 L430 207 L660 65 M195 350 L430 207 L660 350"/></svg><div class="g-node" style="left:8px;top:16px" data-appear="0"><b>区块</b><span>前景 · 控件归属</span></div><div class="g-node" style="right:0;top:16px" data-appear="1"><b>功能</b><span>目的 · 参数 · 条件</span></div><div class="g-node center" style="left:306px;top:153px"><b>冻结的功能知识</b><span>来源版本与摘要固定</span></div><div class="g-node" style="left:8px;bottom:8px" data-appear="1"><b>真实动作关系</b><span>按执行与观察登记</span></div><div class="g-node" style="right:0;bottom:8px" data-appear="2"><b>来源证据</b><span>成功 · 失败 · 未确认</span></div></div>${side(s)}`;
 if(s.kind==='branch')return `<div class="branch-area"><div class="top">定位“六月报表”邮件 → 观察附件条件</div><div class="branch-path" data-appear="1">有附件 ↓<br><strong>回复确认收到</strong><small>“已收到附件，谢谢。”</small></div><div class="branch-path alt" data-appear="1">无附件 ↓<br><strong>回复请求补发</strong><small>不能同时执行两个分支</small></div><div class="bottom" data-appear="2">↓ 共同后续<br>添加已有“报表待核对”标签 → 归档</div></div>${side(s)}`;
 if(s.kind==='outro')return `<div class="outro"><h2>让探索得到的知识，<br>真正服务下一次用户目标。</h2><div class="outro-row">${s.beats.map((b,i)=>`<div class="outro-item" data-appear="${i}"><small>0${i+1}</small><b>${b[0]}</b><p>${b[1]}</p></div>`).join('')}</div></div>`;
 const visual=`<div class="visual" ${s.kind==='event'?'style="width:830px;left:95px"':''}>${picture(s.asset,{w:900,h:s.kind==='event'?475:452})}</div>`;
 let extra='';
 if(s.kind==='tasks')extra='<div class="task-float" data-appear="1"><small>探索任务 · 人工编排示意</small><h3>调查输出设备的可选项</h3><p>未知点：可选设备及适用条件<br>期望产物：观察到的参数事实</p></div>';
 if(s.kind==='goal')extra='<div class="instruction" data-appear="1"><small>共同用户目的 → 自然指令示意</small><p>安排一次小组会议，<br>设置日期与时间，然后保存。</p><div class="chips"><span>同一会议对象</span><span>日期与时间</span><span>保存后核验</span></div></div>';
 if(s.kind==='verify')extra='<div class="verify-overlay" data-appear="1"><h3>需要检查什么？</h3><div>□ 目标事件确实存在</div><div>□ 日期与时间符合要求</div><div>□ 保存后的状态可观察</div><small>检查清单示意，不是本次通过结果。</small></div>';
 return visual+extra+side(s);
}
function build(index){
 sceneIndex=index;beatIndex=-1;const s=SCENES[index];
 $('#scene').innerHTML=`${s.kind==='intro'?'':`<h1 class="scene-title">${s.title}</h1><div class="stage-label">${s.app}</div>`}${mainVisual(s)}<div class="illustration-label">regrow / 框线、光标与卡片为讲解标注</div>`;
 $('#assetCredit').textContent=s.asset?'素材：GNOME 官方应用页面 · © 各应用贡献者 · 来源见说明':'逻辑与关系图为方法示意 · 尚未完成的研究验证不作成功声明';
 $('#sceneNumber').textContent=String(index+1).padStart(2,'0')+' / '+SCENES.length+'  ·  regrow';
 document.querySelectorAll('#chapters button').forEach((b,i)=>{b.classList.toggle('active',i===s.chapter);b.setAttribute('aria-current',i===s.chapter?'step':'false');});
 if(s.marks){const svg=$('#scene .screenshot svg');s.marks.forEach((m,i)=>{
 const [x,y,w,h]=m.box,labelY=m.labelPlacement==='bottom'?y+h+9:Math.max(4,y-33),labelW=Math.min(ASSET_SIZES[s.asset][0],Math.max(160,m.label.length*23+22)),labelX=Math.min(x,ASSET_SIZES[s.asset][0]-labelW);
 svg.insertAdjacentHTML('beforeend',`<g data-mark="${i}"><rect class="annotation ${m.color}" x="${x}" y="${y}" width="${w}" height="${h}" rx="7"/><rect class="label-bg" x="${labelX}" y="${labelY}" width="${labelW}" height="32" rx="6"/><text class="mark-label" x="${labelX+10}" y="${labelY+24}">${m.label}</text></g>`);
 });if(s.kind==='event')$('#scene .screenshot').insertAdjacentHTML('beforeend',cursor);}
 document.title=`${index+1}/${SCENES.length} · ${s.title} — regrow 方法动画`;
}
function render(){
 let i=starts.findIndex((x,j)=>time>=x&&time<(starts[j+1]??total));if(i<0)i=SCENES.length-1;
 if(i!==sceneIndex)build(i);
 const s=SCENES[i],local=clamp(time-starts[i],0,s.duration),beat=Math.min(2,Math.floor(local/4));
 if(beat!==beatIndex){beatIndex=beat;$('#subtitle').textContent=s.captions[beat];}
 document.querySelectorAll('[data-beat]').forEach(el=>{const j=+el.dataset.beat,p=smooth((local-j*4)/.8);el.style.opacity=String(.28+.72*p);el.style.transform=`translateX(${reduced?0:18*(1-p)}px)`;el.classList.toggle('current',j===beat);});
 document.querySelectorAll('[data-appear]').forEach(el=>{const j=+el.dataset.appear,p=smooth((local-j*3.4)/1);el.style.opacity=String(p);el.style.transform=`translateY(${reduced?0:22*(1-p)}px) scale(${reduced?1:.96+.04*p})`;});
 document.querySelectorAll('[data-mark]').forEach(el=>{const j=+el.dataset.mark,p=smooth((local-j*3.7)/.8);el.style.opacity=String(p);el.querySelector('rect').style.strokeDashoffset=String(reduced?0:-local*5);});
 const pic=$('#scene .visual .screenshot');if(pic&&s.kind!=='event'&&s.kind!=='knowledge')pic.style.transform=`scale(${reduced?1:1+.014*Math.sin(Math.min(local/12,1)*Math.PI)})`;
 const c=$('#scene .cursor');if(c){const [w,h]=ASSET_SIZES[s.asset],m=s.marks[Math.min(2,beat)],[x,y,bw,bh]=m.box;const k=pic.offsetWidth/w;c.style.left=(x+bw*.75)*k+'px';c.style.top=(y+bh*.5)*k+'px';c.style.opacity=String(smooth(local/.8));c.style.transition=playing&&!reduced?'left .8s ease,top .8s ease':'none';}
 document.querySelectorAll('.graph-line').forEach(el=>el.style.strokeDashoffset=String(reduced?0:-local*10));
 $('#seek').value=String(time);$('#seek').style.backgroundSize=(time/total*100)+'%';$('#time').textContent=format(time)+' / '+format(total);
 $('#previous').disabled=i===0;$('#next').disabled=i===SCENES.length-1;
}
function seek(value){time=clamp(value,0,total);render();history.replaceState(null,'','#'+(sceneIndex+1));}
function setPlaying(value){playing=value;last=0;$('#play').innerHTML=playing?'Ⅱ <span>暂停</span>':'▶ <span>播放讲解</span>';$('#play').setAttribute('aria-label',playing?'暂停':'播放');$('#play').setAttribute('aria-pressed',String(playing));}
function toggle(){if(time>=total)seek(0);setPlaying(!playing);}
function tick(now){if(playing&&last){time+=Math.min((now-last)/1000,.2)*rate;if(time>=total){time=total;setPlaying(false);}render();}last=now;requestAnimationFrame(tick);}
function fit(){const full=!!document.fullscreenElement,parent=$('#viewport').parentElement,style=getComputedStyle(parent),w=Math.min(parent.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),1440),available=Math.max(180,innerHeight-(full?130:205)),scale=Math.min(w/1440,available/810);$('#viewport').style.width=1440*scale+'px';$('#viewport').style.height=810*scale+'px';$('#stage').style.transform=`scale(${scale})`;}
$('#chapters').innerHTML=CHAPTERS.map((c,i)=>`<button data-chapter="${i}">${c}</button>`).join('');
document.querySelectorAll('[data-chapter]').forEach(b=>b.onclick=()=>seek(starts[SCENES.findIndex(s=>s.chapter===+b.dataset.chapter)]));
$('#play').onclick=toggle;$('#seek').max=String(total);$('#seek').oninput=e=>seek(+e.target.value);
$('#previous').onclick=()=>seek(starts[Math.max(0,sceneIndex-1)]);$('#next').onclick=()=>seek(starts[Math.min(SCENES.length-1,sceneIndex+1)]);
$('#speed').onchange=e=>rate=+e.target.value;
$('#sourcesButton').onclick=()=>{setPlaying(false);$('#sources').showModal();};$('#closeSources').onclick=()=>$('#sources').close();
$('#fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await $('main').requestFullscreen();}catch{$('.hint').textContent='此浏览器暂不支持全屏，请使用浏览器的全屏功能。';}};
document.addEventListener('keydown',e=>{if(e.altKey||e.ctrlKey||e.metaKey||document.querySelector('dialog[open]')||/INPUT|SELECT|TEXTAREA|BUTTON/.test(e.target.tagName))return;if(e.key===' '){e.preventDefault();toggle();}else if(e.key==='ArrowRight'){e.preventDefault();$('#next').click();}else if(e.key==='ArrowLeft'){e.preventDefault();$('#previous').click();}});
document.addEventListener('visibilitychange',()=>{if(document.hidden)setPlaying(false);});
window.addEventListener('resize',fit);document.addEventListener('fullscreenchange',fit);
window.addEventListener('hashchange',()=>{const n=Number(location.hash.slice(1));seek(starts[clamp(Number.isInteger(n)?n-1:0,0,SCENES.length-1)]);});
// Expose deterministic seeking for presentation verification and optional recording.
window.film={seek,setPlaying,getTime:()=>time,getScene:()=>sceneIndex,total};
const first=Number(location.hash.slice(1));seek(starts[clamp(Number.isInteger(first)&&first>0?first-1:0,0,SCENES.length-1)]);fit();requestAnimationFrame(tick);
