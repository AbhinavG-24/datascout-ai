const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const api=async(u,m='GET',b)=>{const r=await fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});if(!r.ok)throw new Error((await r.json().catch(()=>({}))).detail||r.statusText);return r.json()};
const RUN=['queued','planning','discovering','collecting','validating'];
const S={tasks:[],cur:null,t:null,tab:'data',q:'',chip:'',dom:'',minc:0,sort:null,dir:1,page:1,size:25,sel:new Set(),tq:''};
const TPL=[['💼 Jobs','Find open ML engineer jobs at AI startups in Bengaluru: company, role, location, apply link'],['🤝 Sponsors','Tech conferences in India seeking sponsors: event, organiser, sponsor tiers, contact page'],['📈 Leads','B2B SaaS companies in Delhi NCR that could buy a cybersecurity product: company, size, website, contact'],['🎓 Programs','Open-source student internship programs: program, organisation, deadline, apply link']];
function toast(m){const t=$('#toast');t.textContent=m;t.style.display='block';clearTimeout(t._h);t._h=setTimeout(()=>t.style.display='none',2500)}
$('#tpl').innerHTML=TPL.map((t,i)=>`<span class="chip" data-i="${i}">${t[0]}</span>`).join('');
$$('#tpl .chip').forEach(c=>c.onclick=()=>$('#p').value=TPL[c.dataset.i][1]);
document.documentElement.dataset.theme=localStorage.theme||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
$('#theme').onclick=()=>{const d=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=d;try{localStorage.theme=d}catch(e){}};
document.addEventListener('keydown',e=>{if(e.key==='/'&&!/INPUT|TEXTAREA/.test(document.activeElement.tagName)){e.preventDefault();($('#q')||$('#p')).focus()}});
$('#tq').oninput=e=>{S.tq=e.target.value.toLowerCase();renderList()};

$('#go').onclick=async()=>{
 const p=$('#p').value.trim();if(!p)return toast('Describe what you need first');
 try{const r=await api('/api/tasks','POST',{prompt:p,fields:$('#fld').value.split(',').map(x=>x.trim()).filter(Boolean),max_pages:+$('#mp').value,depth:+$('#dp').value,interval:+$('#iv').value,delay:+$('#dl').value});
  $('#p').value='';select(r.id);toast('Workflow started')}catch(e){toast(e.message)}};

async function boot(){const h=await api('/api/health');$('#ai').textContent=h.ai?'AI mode · '+h.model:'Heuristic mode (no API key)';$('#ai').style.color=h.ai?'var(--ok)':'var(--wn)';loop()}
async function loop(){
 try{S.tasks=await api('/api/tasks');renderList();const s=await api('/api/summary');$('#sum').textContent=`${s.tasks} tasks · ${s.records} records · ${s.sources} domains`;
  if(S.cur){S.t=await api('/api/tasks/'+S.cur);paint()}}catch(e){}
 setTimeout(loop,S.t&&RUN.includes(S.t.status)?1200:4000)}
function renderList(){
 const l=S.tasks.filter(t=>!S.tq||(t.title+t.prompt).toLowerCase().includes(S.tq));
 $('#tl').innerHTML=l.map(t=>`<div class="tk ${t.id==S.cur?'s':''}" data-i="${t.id}"><b>${esc(t.title)}</b><span class="st ${t.status}">${t.status}</span> <span class="m">${t.counts.n||0} rows${t.counts.new?` · <span class="new">${t.counts.new} new</span>`:''}${t.interval?' · ⏱'+t.interval+'m':''}</span></div>`).join('')||'<div class="m">No tasks yet.</div>';
 $$('.tk').forEach(x=>x.onclick=()=>select(+x.dataset.i))}
async function select(id){S.cur=id;S.t=null;S.sel.clear();S.page=1;S.q=S.chip=S.dom='';S.minc=0;S.sort=null;$('#view').innerHTML='<div class="card m">Loading…</div>';S.t=await api('/api/tasks/'+id);shell();paint();renderList()}

function shell(){
 $('#view').innerHTML=`<div class="card"><div class="r sp"><h2 id="ttl" style="margin:0"></h2><div class="r" style="margin:0" id="acts"></div></div><div class="m" id="sub"></div><div id="err"></div><div class="stats" id="stats"></div>
 <div class="tabs">${[['data','Dataset'],['src','Sources'],['ana','Analytics'],['log','Workflow log'],['plan','Plan']].map(([k,l])=>`<div class="tab" data-k="${k}">${l}</div>`).join('')}</div>
 <div id="bar"><div class="r"><input id="q" placeholder="Search all fields…  ( / )" style="flex:2;min-width:180px"><select id="dom" style="flex:1"></select><label class="r" style="margin:0">Min conf <input id="mc" type="range" min="0" max="100" value="0" style="width:90px"><span id="mcv">0%</span></label></div>
  <div class="r" id="chips"></div></div><div id="body"></div></div>`;
 $$('.tab').forEach(x=>x.onclick=()=>{S.tab=x.dataset.k;paint()});
 $('#q').oninput=e=>{S.q=e.target.value;S.page=1;paintBody()};$('#dom').onchange=e=>{S.dom=e.target.value;S.page=1;paintBody()};
 $('#mc').oninput=e=>{S.minc=+e.target.value;$('#mcv').textContent=S.minc+'%';S.page=1;paintBody()}}
function paint(){
 const t=S.t;if(!t||!$('#ttl'))return;const st=t.stats||{},run=RUN.includes(t.status),n=t.records.filter(r=>r.status!=='removed').length;
 $('#ttl').innerHTML=`${esc(t.title)} <span class="st ${t.status}">${t.status}</span>`;
 $('#sub').innerHTML=`${esc(t.prompt)}<br>Planner: ${esc(t.plan.mode||'…')} · Run #${t.runs} · Updated ${esc(t.updated.slice(0,19).replace('T',' '))} UTC${t.interval?` · auto every ${t.interval} min`:''}`;
 $('#err').innerHTML=t.error?`<div class="error">${esc(t.error)}</div>`:'';
 $('#acts').innerHTML=(run?'<button id="cx">■ Cancel</button>':'<button id="rr">↻ Re-run</button>')+`<button id="cl">⧉ Clone</button><button id="sc">⏱ Schedule</button><select id="fmt" style="width:80px"><option>csv</option><option>json</option><option>ndjson</option></select><button id="ex">⬇ Export</button><button id="dt" class="d">Delete</button>`;
 $('#cx')&&($('#cx').onclick=()=>api(`/api/tasks/${t.id}/cancel`,'POST'));$('#rr')&&($('#rr').onclick=()=>{api(`/api/tasks/${t.id}/rerun`,'POST');toast('Re-running…')});
 $('#cl').onclick=async()=>select((await api(`/api/tasks/${t.id}/clone`,'POST')).id);
 $('#sc').onclick=async()=>{const v=prompt('Re-run every N minutes (0 = off). New / changed / removed rows are flagged on each run.',t.interval);if(v!==null){await api('/api/tasks/'+t.id,'PATCH',{interval:+v||0});toast('Schedule saved')}};
 $('#ex').onclick=()=>{const ids=S.sel.size?[...S.sel]:(filtered().length<n?filtered().map(r=>r.id):[]);location.href=`/api/tasks/${t.id}/export?fmt=${$('#fmt').value}${ids.length?'&ids='+ids.join(','):''}`};
 $('#dt').onclick=async()=>{if(confirm('Delete this task and all its data?')){await api('/api/tasks/'+t.id,'DELETE');S.cur=S.t=null;$('#view').innerHTML='';toast('Deleted')}};
 $('#stats').innerHTML=[[n,'records'],[st.pages||0,'pages fetched'],[st.raw||0,'raw extracted'],[st.duplicates||0,'duplicates removed'],[st.blocked||0,'blocked by robots'],[st.failed||0,'failed'],[st.new||0,'new this run'],[st.changed||0,'changed']].map(([v,l])=>`<div class="stat"><b>${v}</b>${l}</div>`).join('');
 $$('.tab').forEach(x=>x.classList.toggle('on',x.dataset.k===S.tab));$('#bar').style.display=S.tab==='data'?'':'none';
 const doms=[...new Set(t.records.map(r=>host(r.source_url)))];$('#dom').innerHTML='<option value="">All sources</option>'+doms.map(d=>`<option ${d===S.dom?'selected':''}>${esc(d)}</option>`).join('');
 const cnt=k=>t.records.filter(r=>k==='flagged'?r.flags.length:k==='starred'?r.starred:r.status===k).length;
 $('#chips').innerHTML=['new','changed','removed','flagged','starred'].map(k=>`<span class="chip ${S.chip===k?'on':''}" data-k="${k}">${k} (${cnt(k)})</span>`).join('');
 $$('#chips .chip').forEach(c=>c.onclick=()=>{S.chip=S.chip===c.dataset.k?'':c.dataset.k;S.page=1;paint()});paintBody()}
const host=u=>{try{return new URL(u).hostname}catch(e){return ''}};
function filtered(){const q=S.q.toLowerCase();let rs=S.t.records.filter(r=>(S.chip==='removed'?r.status==='removed':r.status!=='removed'||false)&&(!q||JSON.stringify(r.data).toLowerCase().includes(q)||r.source_url.toLowerCase().includes(q))
  &&(!S.dom||host(r.source_url)===S.dom)&&r.conf*100>=S.minc&&(!S.chip||S.chip==='removed'||(S.chip==='flagged'?r.flags.length:S.chip==='starred'?r.starred:r.status===S.chip)));
 if(S.sort)rs.sort((a,b)=>{const g=r=>S.sort==='conf'?r.conf:S.sort==='src'?host(r.source_url):r.data[S.sort]??'';return String(g(a)).localeCompare(String(g(b)),undefined,{numeric:true})*S.dir});return rs}
function paintBody(){const b=$('#body'),t=S.t;({data:pData,src:pSrc,ana:pAna,log:pLog,plan:pPlan})[S.tab](b,t)}
function pData(b,t){
 const cols=t.plan.schema||[],rs=filtered(),pages=Math.max(1,Math.ceil(rs.length/S.size));S.page=Math.min(S.page,pages);const pg=rs.slice((S.page-1)*S.size,S.page*S.size);
 b.innerHTML=`<div class="r sp"><span class="m">${rs.length} rows · ${S.sel.size} selected</span><div class="r" style="margin:0"><button id="bs">★ Star</button><button id="bd" class="d">Delete selected</button></div></div>
 <div class="tb"><table><thead><tr><th><input type="checkbox" id="all"></th>${cols.map(c=>`<th data-k="${c.key}">${esc(c.label)} ${S.sort===c.key?(S.dir>0?'▲':'▼'):'↕'}</th>`).join('')}<th data-k="conf">Conf</th><th data-k="src">Source</th><th>Status</th></tr></thead><tbody>
 ${pg.map(r=>`<tr class="x ${r.status==='removed'?'rm':''}" data-i="${r.id}"><td><input type="checkbox" class="ck" ${S.sel.has(r.id)?'checked':''}></td>${cols.map(c=>`<td>${cell(c.key,r.data[c.key],r.prev)}</td>`).join('')}<td>${Math.round(r.conf*100)}%${r.flags.length?' ⚠':''}</td><td><a href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(host(r.source_url))}</a></td><td>${r.starred?'★ ':''}<span class="tag ${r.status}">${r.status}</span></td></tr>`).join('')||`<tr><td colspan="${cols.length+4}" class="m">${RUN.includes(t.status)?'Collecting…':'No rows match.'}</td></tr>`}</tbody></table></div>
 <div class="r sp" style="margin-top:8px"><span><button id="pp">‹</button> Page ${S.page}/${pages} <button id="pn">›</button></span><select id="ps" style="width:90px">${[10,25,50,100].map(n=>`<option ${n===S.size?'selected':''}>${n}</option>`).join('')}</select></div>`;
 $('#pp').onclick=()=>{S.page=Math.max(1,S.page-1);paintBody()};$('#pn').onclick=()=>{S.page=Math.min(pages,S.page+1);paintBody()};$('#ps').onchange=e=>{S.size=+e.target.value;S.page=1;paintBody()};
 $('#all').onchange=e=>{pg.forEach(r=>e.target.checked?S.sel.add(r.id):S.sel.delete(r.id));paintBody()};
 $$('.ck',b).forEach(c=>c.onclick=e=>{e.stopPropagation();const id=+c.closest('tr').dataset.i;c.checked?S.sel.add(id):S.sel.delete(id);$$('.m',b)[0].textContent=`${rs.length} rows · ${S.sel.size} selected`});
 $$('th[data-k]',b).forEach(h=>h.onclick=()=>{S.dir=S.sort===h.dataset.k?-S.dir:1;S.sort=h.dataset.k;paintBody()});
 $$('tr.x',b).forEach(tr=>tr.onclick=e=>{if(e.target.tagName!=='A'&&e.target.type!=='checkbox')inspect(+tr.dataset.i)});
 $('#bs').onclick=async()=>{await api('/api/records/bulk','POST',{action:'star',ids:[...S.sel]});toast('Starred');refresh()};
 $('#bd').onclick=async()=>{if(S.sel.size&&confirm(`Delete ${S.sel.size} rows?`)){await api('/api/records/bulk','POST',{action:'delete',ids:[...S.sel]});S.sel.clear();refresh()}}}
const cell=(k,v,prev)=>{v=v??'';const u=/^https?:\/\//.test(v)?`<a href="${esc(v)}" target="_blank" rel="noopener">${esc(v.length>40?v.slice(0,40)+'…':v)}</a>`:esc(v);return u};
const refresh=async()=>{S.t=await api('/api/tasks/'+S.cur);paint()};
function inspect(id){
 const r=S.t.records.find(x=>x.id===id),cols=S.t.plan.schema,d=$('#dlg');
 d.innerHTML=`<h2>Record inspector</h2><div class="m">Method: ${esc(r.method)} · Confidence ${Math.round(r.conf*100)}% · Fetched ${esc(r.fetched_at)} · First seen ${esc(r.first_seen)}</div>
 ${cols.map(c=>`<label>${esc(c.label)}${r.prev&&r.prev[c.key]!==r.data[c.key]?` <span class="diff">was: ${esc(r.prev[c.key])}</span>`:''}<input data-k="${c.key}" value="${esc(r.data[c.key])}"></label>`).join('')}
 <p><b>Source:</b> <a href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(r.source_url)}</a></p><p><b>Evidence:</b> <i>${esc(r.evidence||'—')}</i></p><p><b>Validation flags:</b> ${esc(r.flags.join('; ')||'none')}</p>
 <div class="r"><button class="p" id="sv">Save edits</button><button id="st">${r.starred?'★ Unstar':'☆ Star'}</button><button class="d" id="rd">Delete</button><button id="cc">Close</button></div>`;
 d.showModal();$('#cc').onclick=()=>d.close();
 $('#sv').onclick=async()=>{const data={};$$('input[data-k]',d).forEach(i=>data[i.dataset.k]=i.value);await api('/api/records/'+id,'PATCH',{data});d.close();toast('Saved (marked manual, 100%)');refresh()};
 $('#st').onclick=async()=>{await api('/api/records/'+id,'PATCH',{starred:!r.starred});d.close();refresh()};
 $('#rd').onclick=async()=>{await api('/api/records/'+id,'DELETE');d.close();refresh()}}
function pSrc(b,t){b.innerHTML=`<div class="tb"><table><thead><tr><th>URL</th><th>Status</th><th>HTTP</th><th>Records</th><th>Depth</th><th>Note</th></tr></thead><tbody>${t.sources.map(s=>`<tr><td><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a></td><td><span class="tag ${s.status}">${s.status}</span></td><td>${s.http||''}</td><td>${s.records}</td><td>${s.depth}</td><td>${esc(s.note||'')}</td></tr>`).join('')||'<tr><td colspan="6" class="m">No sources yet.</td></tr>'}</tbody></table></div>`}
function pLog(b,t){b.innerHTML=`<pre>${t.logs.map(l=>`${l.ts.slice(11,19)}  <span class="${l.level}">${esc(l.msg)}</span>`).join('\n')}</pre>`}
function pPlan(b,t){b.innerHTML=`<pre>${esc(JSON.stringify(t.plan,null,2))}</pre><p class="m">Options: ${esc(JSON.stringify(t.opts))}</p>`}
function pAna(b,t){
 const rs=t.records.filter(r=>r.status!=='removed'),by=(f)=>{const m={};rs.forEach(r=>{const k=f(r);m[k]=(m[k]||0)+1});return Object.entries(m).sort((a,b)=>b[1]-a[1])};
 const bars=(a,max)=>a.map(([k,v])=>`<div class="row2"><span>${esc(k)}</span><div class="bar" style="width:${v/max*100}%"></div><span>${v}</span></div>`).join('')||'<span class="m">No data</span>';
 const conf=by(r=>Math.min(9,Math.floor(r.conf*10))*10+'–'+(Math.min(9,Math.floor(r.conf*10))*10+10)+'%').sort(),dom=by(r=>host(r.source_url)).slice(0,8),meth=by(r=>r.method),stt=by(r=>r.status);
 const cols=['#4f46e5','#15803d','#b45309','#0369a1','#b91c1c'];let acc=0;const tot=rs.length||1;
 const grad=stt.map(([k,v],i)=>{const s=acc;acc+=v/tot*100;return `${cols[i%5]} ${s}% ${acc}%`}).join(',')||'#888 0 100%';
 const ok=rs.filter(r=>!r.flags.length).length;
 b.innerHTML=`<div class="two"><div><h2>Confidence distribution</h2>${bars(conf,Math.max(1,...conf.map(x=>x[1])))}</div><div><h2>Records by source domain</h2>${bars(dom,Math.max(1,...dom.map(x=>x[1])))}</div>
 <div><h2>Extraction method</h2>${bars(meth,Math.max(1,...meth.map(x=>x[1])))}</div><div><h2>Status mix</h2><div class="r"><div class="donut" style="background:conic-gradient(${grad})"></div><div>${stt.map(([k,v],i)=>`<div><span style="color:${cols[i%5]}">●</span> ${k}: ${v}</div>`).join('')}</div></div></div>
 <div><h2>Data quality</h2><p><b>${rs.length?Math.round(ok/rs.length*100):0}%</b> of rows passed all validation checks (${ok}/${rs.length}).</p><p class="m">Checks: entity name present, field completeness, email/URL format, evidence found on page (AI mode), fuzzy de-duplication.</p></div></div>`}
boot();
