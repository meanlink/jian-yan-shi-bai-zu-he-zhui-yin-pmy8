import {esc,fmt} from '../../utils/dom.js';
import {Verdict} from '../../constants/enums.js';
import {ITEMS_LABELS} from '../../constants/assay-ui.js';

const ITEM_KEYS=Object.keys(ITEMS_LABELS);

function verdictBadge(v){
 return '<span class="verdict '+esc(v)+'">'+esc(Verdict[v]||v)+'</span>';
}

function completionTable(completions){
 const cols=[{key:'batch_id',label:'批次'},...ITEM_KEYS.map(k=>({key:k,label:ITEMS_LABELS[k]}))];
 return '<div class="table-wrap mini-scroll"><table><thead><tr>'+cols.map(c=>'<th>'+esc(c.label)+'</th>').join('')+'</tr></thead><tbody>'
  +completions.map(r=>'<tr>'+cols.map(c=>{
    if(c.key==='batch_id')return '<td>'+esc(r[c.key])+'</td>';
    const v=r[c.key];
    return '<td class="'+(v===null||v===undefined?'unknown-cell':'')+'">'+esc(v===null||v===undefined?'未知':v)+'</td>';
  }).join('')+'</tr>').join('')+'</tbody></table></div>';
}

function witnessBlock(title,w){
 if(!w)return '';
 const c=w.counts;
 return '<h4>'+esc(title)+'：共同失败 '+c.joint+' 批 · 支持度 '+fmt(w.support_pct)+'% · 置信度 '+fmt(w.confidence_pct)+'% · 提升度 '+fmt(w.lift)+'</h4>'
  +completionTable(w.completions);
}

function ruleRow(j){
 let metrics='';
 let witness='';
 if(j.verdict==='certain'){
  metrics='最差可行补全：支持度 '+fmt(j.worst_support_pct)+'% · 置信度 '+fmt(j.worst_confidence_pct)+'% · 提升度 '+fmt(j.worst_lift);
  witness='<details class="witness-details"><summary>查看必然成立的逐批补全（'+j.certain_completion.length+' 批）<span>展开</span></summary><div class="witness-body">'+completionTable(j.certain_completion)+'</div></details>';
 }else if(j.verdict==='possible'){
  metrics='入选见证 提升度 '+fmt(j.pass_witness.lift)+' / 落选见证 提升度 '+fmt(j.fail_witness.lift);
  witness='<details class="witness-details"><summary>逐批补全核对：入选与落选各一份（各 '+j.pass_witness.completions.length+' 批）<span>展开</span></summary><div class="witness-body">'
   +witnessBlock('入选补全（过阈值）',j.pass_witness)
   +witnessBlock('落选补全（不过阈值）',j.fail_witness)+'</div></details>';
 }else{
  metrics='最优可行补全仍落选：支持度 '+fmt(j.best_support_pct)+'% · 置信度 '+fmt(j.best_confidence_pct)+'% · 提升度 '+fmt(j.best_lift);
 }
 return '<tr><td>'+esc(j.rule_id)+'</td><td>'+verdictBadge(j.verdict)+'</td><td>'+esc(j.antecedent)+' → '+esc(j.consequent)+'</td><td>'+metrics+'</td></tr>'
  +(witness?'<tr><td colspan="4" style="padding-top:0">'+witness+'</td></tr>':'');
}

export function partialResults(r,j){
 const groups=r.groups||{};
 const order=['certain','possible','impossible'];
 const progress=j.progress?('<div class="progress-line"><span>规则判定进度</span><div class="progress-track"><div class="progress-fill" style="width:'+(j.progress.total?Math.round(j.progress.judged/j.progress.total*100):0)+'%"></div></div><span>'+j.progress.judged+' / '+j.progress.total+'</span></div>'):'';
 return '<section class="result-lead"><p class="eyebrow">PARTIAL / LEGACY INSTRUMENT</p><h2>'+esc(r.summary)+'</h2>'
  +'<div class="metrics">'+(r.metrics||[]).map(m=>'<div><span>'+esc(m.label)+'</span><strong>'+esc(fmt(m.value))+'</strong></div>').join('')+'</div>'
  +(progress?'<div style="margin-top:18px">'+progress+'</div>':'')+'</section>'
  +'<section class="panel"><div class="section-title"><h2>判定口径</h2><span>支持度阈值 '+fmt(r.thresholds?.min_support)+' · 置信度阈值 '+fmt(r.thresholds?.min_confidence)+'</span></div><p class="hint">'+esc(r.method)+'</p>'
  +(r.warnings||[]).map(w=>'<p class="warning">'+esc(w)+'</p>').join('')+'</section>'
  +order.map(v=>(groups[v]?.length?('<section class="verdict-group"><h3>'+verdictBadge(v)+'<small>'+Verdict[v]+' · '+groups[v].length+' 条候选规则</small></h3><div class="table-wrap"><table><thead><tr><th>编号</th><th>判定</th><th>规则（前项 → 后项）</th><th>边界指标 / 见证</th></tr></thead><tbody>'+groups[v].map(ruleRow).join('')+'</tbody></table></div></section>'):'')).join('')
  +'<section class="panel"><div class="section-title"><h2>业务解释</h2></div><ol class="questions">'+(r.findings||[]).map(x=>'<li>'+esc(x)+'</li>').join('')+'</ol></section>';
}
