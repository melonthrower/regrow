 'use strict';
const DATA=[
 {name:'应用遍历与功能图',sub:'Desktop + Android',cells:[['green','遍历链路已跑通','发现、动作执行、图更新与保存'],['green','多应用运行已跑通','持续产出应用遍历图'],['amber','已跑通 23 / 30 个应用','其余 7 个仍在推进；图结构待统一校对']],status:'持续扩量'},
 {name:'目标驱动任务生成',sub:'功能图 → 复杂用户指令',cells:[['green','生成链路已跑通','读取功能及条件，组织用户目标'],['green','任务生成已跑通','支持后续批量采集'],['amber','开展数据质量抽检','检查合理性、多功能比例与可执行性']],status:'持续生成'},
 {name:'实时轨迹采集',sub:'Desktop 3,000 · Mobile 4,000',cells:[['green','采集链路已跑通','图指导执行与轨迹保存'],['green','已采集 2,262 条','桌面 1,327；移动端 935'],['amber','继续扩量与质量核验','桌面待采 1,673；移动端待采 3,065']],status:'持续采集'},
 {name:'Qwen3-VL 微调',sub:'本工作数据 → 模型训练',cells:[['green','微调 pipeline 已跑通','训练数据接入与训练流程'],['green','100 步轨迹验证完成','小规模 pipeline 验证'],['amber','下一步开展数据微调','冻结数据划分，训练并保存 checkpoint']],status:'小试完成'},
 {name:'下游主评测',sub:'OSWorld + AndroidWorld',cells:[['green','双基准测试已跑通','Qwen3-VL 测试入口已接通'],['green','两端评测流程已跑通','桌面 OSWorld；移动 AndroidWorld'],['amber','下一步形成主结果表','微调后与同类 GUI agent 同条件比较']],status:'流程跑通'}
];
const PLANS=[['E1 · 数据微调','在本工作数据上微调 Qwen3-VL','固定训练 / 验证划分，隔离测试任务；比较原模型与微调模型，保存数据版本、训练配置和 checkpoint。','输出：模型与训练记录'],['E2 · 主结果对比','与同类 GUI agent 比较','在 OSWorld 和 AndroidWorld 使用统一任务、初态、动作接口与预算，报告整体及分类任务成功率。','输出：双基准主结果表'],['E3 · 图指导对照','复杂指令的执行成功率','固定模型、复杂指令与预算，仅改变有无图指导；比较完整业务成功率、执行步数、成本与失败类型。','输出：图指导收益与适用边界']];
document.querySelector('#rows').innerHTML=DATA.map(d=>`<tr><td><div class="work"><strong>${d.name}</strong><small>${d.sub}</small></div></td>${d.cells.map(([c,t,n])=>`<td><div class="stage"><div class="stage-title">${t}</div><div class="bar ${c}"></div><p>${n}</p></div></td>`).join('')}<td><span class="badge">${d.status}</span></td></tr>`).join('');
document.querySelector('#plans').innerHTML=PLANS.map(([id,title,body,measure])=>`<article class="plan-item"><small>${id}</small><h3>${title}</h3><p>${body}</p><p class="measure">${measure}</p></article>`).join('');
const DATASETS=[['SEE-Train','2026 · arXiv v1 · 图结构合成',3237,'14.8','训练集轨迹'],['UI-Genie-Agent-16K','NeurIPS 2025 · 自探索生成',2208,'7.1','轨迹数；16K 指动作样本']];
document.querySelector('#datasetRows').innerHTML=DATASETS.map(([name,sub,count,steps,scope])=>`<div class="dataset-row"><div><strong>${name}</strong><small>${sub}</small></div><div><div class="quantity"><i class="published" style="width:${count/40}%"></i></div><b>${count.toLocaleString('en-US')}</b><small>${scope}</small></div><div><strong>${steps} <em>步</em></strong><small>论文报告均值</small></div></div>`).join('');
const OURS=[['regrow · 桌面端',1327,3000],['regrow · 移动端',935,4000]];
document.querySelector('#ourRows').innerHTML=OURS.map(([name,done,target])=>`<div class="dataset-row ours"><div><strong>${name}</strong><small>功能图指导 · 实时执行采集</small></div><div><div class="quantity segmented" aria-label="已采集 ${done} 条，尚未采集 ${target-done} 条，目标 ${target} 条"><i class="green" style="width:${done/40}%"></i><i class="remaining" style="width:${(target-done)/40}%"></i></div><b>${done.toLocaleString('en-US')} / ${target.toLocaleString('en-US')}</b><small>已采集 / 目标 · 待采 ${(target-done).toLocaleString('en-US')} 条</small></div><div><strong>12–20 <em>步</em></strong><small>预期均值区间 · 非实测</small></div></div>`).join('');
document.querySelector('#print').onclick=()=>window.print();
