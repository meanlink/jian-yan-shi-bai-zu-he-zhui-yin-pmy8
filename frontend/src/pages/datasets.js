import {datasets} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';
import {DatasetKind} from '../constants/enums.js';

function kindTag(d){
 const legacy=d.kind==='legacy';
 return '<span class="kind-tag'+(legacy?' legacy':'')+'">'+esc(DatasetKind[d.kind]||DatasetKind.full)+'</span>';
}

export async function dataPage(){
 workspace.datasets=await datasets.list();
 let selected=workspace.datasets[0]?await datasets.get(workspace.datasets[0].id):null,m=workspace.meta;
 const legacyColumns=[
  {key:'batch_id',label:'复检批次'},
  {key:'fail_total',label:'失败项总数'},
  ...m.columns.filter(c=>c.key!=='batch_id').map(c=>({key:c.key,label:c.label+'(可留空)'})),
 ];
 return heading('02 / DATA INTAKE','数据接入与批次追溯','完整五项数据按原口径校验；旧仪器仅存失败总数与部分单项，已知项与总数对不上即整批拒收。分析任务始终绑定提交时的不可变数据版本。')
 +'<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>业务批次</h2><span>'+workspace.datasets.length+' 批</span></div>'
 +'<div class="batch-list">'+workspace.datasets.map(d=>'<button class="batch-item" data-dataset="'+d.id+'"><strong>'+esc(d.name)+' '+kindTag(d)+'</strong><span>'+d.rows+' 条 · '+esc(d.source)+'</span><small>SHA256 '+esc(d.checksum.slice(0,18))+'…</small>'+(d.version_of_id?'<p class="version-note">补录版本 · 源自批次 #'+d.version_of_id+' · '+esc(d.version_note||'')+'</p>':'')+'</button>').join('')+'</div>'
 +'<div class="section-title"><h2>接入新数据</h2></div>'
 +'<div class="progress-line" style="margin-bottom:16px"><label style="margin:0"><input type="radio" name="import-mode" value="full" checked style="width:auto"> 完整五项 0/1</label><label style="margin:0"><input type="radio" name="import-mode" value="legacy" style="width:auto"> 旧仪器（fail_total+部分单项）</label></div>'
 +'<form id="dataset-form"><label>批次名称<input name="name" required minlength="2" placeholder="例如：11 月旧仪器导入批次"></label><label>上传 CSV 或 JSON<input type="file" id="file-input" accept=".json,.csv"></label><label>记录 JSON<textarea name="records" rows="6" placeholder="完整数据粘贴五项 0/1；旧仪器数据含 fail_total，未知单项留空或 null" required></textarea></label><p class="hint" id="import-hint">完整数据字段：'+m.columns.map(c=>esc(c.key)).join('，')+'。5–5,000 条记录。</p><button type="submit" class="primary" '+(session.user.role==='viewer'?'disabled':'')+'>校验并接入批次</button></form>'
 +(selected&&selected.kind==='legacy'?'<div class="section-title" style="margin-top:26px"><h2>补录后另存新版本</h2></div><form id="version-form"><label>新版本名称<input name="name" required minlength="2" placeholder="例如：旧仪器批次补录完整版"></label><label>补录记录 JSON（完整五项 0/1）<textarea name="records" rows="4" required></textarea></label><p class="hint">原批次保持不变，补录数据另存为带谱系的新版本，可在工作台基于它重新计算。</p><button type="submit" class="primary" '+(session.user.role==='viewer'?'disabled':'')+'>另存并重算入口</button></form>':'')
 +'</section><section class="panel"><div class="section-title"><h2 id="preview-name">'+esc(selected?.name||'尚无批次')+'</h2><span>'+(selected?kindTag(selected):'')+' 预览前 30 条</span></div><div id="data-preview">'+table(selected?.kind==='legacy'?legacyColumns:m.columns,selected?.records.slice(0,30)||[])+(selected?.kind==='legacy'?'<p class="hint">留空单元格表示旧仪器未测单项；fail_total 为该批失败项总数，导入时已逐批校验可行补全。</p>':'')+'</div></section></div>';
}

export function bindData(refresh){
 let source='manual.json';
 const mode=()=>document.querySelector('input[name="import-mode"]:checked')?.value||'full';
 document.querySelectorAll('input[name="import-mode"]').forEach(r=>r.addEventListener('change',()=>{
  const hint=document.querySelector('#import-hint');
  hint.textContent=mode()==='legacy'
   ?'旧仪器字段：batch_id、fail_total(0~5 整数) 与部分检验项；未知项留空或 null，至少一项已知。'
   :'完整数据字段：'+workspace.meta.columns.map(c=>c.key).join('，')+'。5–5,000 条记录。';
 }));
 document.querySelector('#file-input').addEventListener('change',async e=>{
  try{
   const file=e.target.files[0];if(!file)return;source=file.name;
   const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);
   document.querySelector('[name=records]').value=JSON.stringify(records,null,2);
  }catch(error){notify(error.message,true);}
 });
 document.querySelectorAll('[data-dataset]').forEach(button=>button.onclick=async()=>{
  try{
   const d=await datasets.get(button.dataset.dataset);
   const m2=workspace.meta;
   const legacyColumns=[{key:'batch_id',label:'复检批次'},{key:'fail_total',label:'失败项总数'},...m2.columns.filter(c=>c.key!=='batch_id').map(c=>({key:c.key,label:c.label}))];
   document.querySelector('#preview-name').textContent=d.name;
   document.querySelector('#data-preview').innerHTML=table(d.kind==='legacy'?legacyColumns:m2.columns,d.records.slice(0,30));
  }catch(error){notify(error.message,true);}
 });
 submit(document.querySelector('#dataset-form'),async f=>{
  const payload={name:f.get('name'),source,records:JSON.parse(f.get('records'))};
  if(mode()==='legacy'){await datasets.createLegacy(payload);notify('旧仪器数据已逐批校验并接入');}
  else{await datasets.create(payload);notify('数据已接入，可前往工作台执行分析');}
  await refresh();
 });
 const versionForm=document.querySelector('#version-form');
 if(versionForm){
  submit(versionForm,async f=>{
   const parent=await datasets.get(workspace.datasets[0].id);
   if(parent.kind!=='legacy')throw new Error('当前批次不是旧仪器部分项数据');
   await datasets.createVersion(parent.id,{name:f.get('name'),source:'manual.json',records:JSON.parse(f.get('records')),version_note:'页面补录另存'});
   notify('补录版本已另存，可在工作台选择新版本重算');
   await refresh();
  });
 }
}
