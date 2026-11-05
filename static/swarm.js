/* Live view of the research swarms. Two tabs share this page:
   #regulations  regulation documents   data/regulations/registry/status.json  (python swarm.py status)
   #gis          town GIS data          data/gis/registry/status.json          (python swarm.py status --kind gis) */
const $=id=>document.getElementById(id), GIS=location.hash==='#gis', R=GIS?'data/gis/registry/':'data/regulations/registry/';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ST=GIS?{found:['Sign layer','--found'],partial:['GIS, no sign layer','--partial'],not_found:['Nothing public','--notfound'],error:['Error','--error'],searching:['Searching','--searching'],queued:['Queued','--queued']}
  :{found:['Mappable doc','--found'],partial:['Partial','--partial'],not_found:['Not found','--notfound'],error:['Error','--error'],searching:['Searching','--searching'],queued:['Queued','--queued']};
const KIND={portal:'ArcGIS org',opendata:'Open data',viewer:'Map viewer',rest:'REST services',layer:'Layer',download:'Download',document:'Document',other:'Other'};
const n=x=>x==null?'':Number(x).toLocaleString();
const RESOLVED=['found','partial','not_found','error'];
let towns={},status=null,prev={},filter='all',selected=null,firstPaint=true;
const fmtT=iso=>iso?new Date(iso).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}):'—';
const dur=s=>{if(!isFinite(s)||s<0)return '—';const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=Math.floor(s%60);return h?`${h}h ${m}m`:m?`${m}m ${x}s`:`${x}s`};
setInterval(()=>$('clock').textContent=new Date().toLocaleTimeString([], {hour12:false}),1000);

async function init(){
  document.querySelectorAll('.tabs a').forEach(a=>{const on=(a.hash==='#gis')===GIS;a.setAttribute('aria-current',on?'page':'false');a.onclick=e=>{e.preventDefault();if(on)return;location.hash=a.hash;location.reload()}});
  if(GIS){$('mission').innerHTML='Finding every Massachusetts town\'s <em>GIS data</em>: portals, viewers, open data and sign layers';$('docs-title').textContent='GIS links';
    $('docs-head').innerHTML='<th>Town</th><th>Best link</th><th>Kind</th><th>Features</th><th>Stop signs</th><th>Found by</th>';
    document.querySelector('.filters').innerHTML='<button data-f="all" aria-pressed="true">All</button><button data-f="found" aria-pressed="false">Sign layers</button><button data-f="partial" aria-pressed="false">GIS only</button>';
    $('csv').hidden=false;document.title='Gnomon Swarm · GIS data'}
  const t=await (await fetch(R+'towns.json')).json(),svg=$('map');svg.setAttribute('viewBox',t.viewbox.join(' '));
  const g=$('towns');
  for(const x of t.towns){towns[x.slug]=x;const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',x.path);p.dataset.slug=x.slug;p.setAttribute('tabindex','-1');
    p.addEventListener('mousemove',e=>tip(e,x.slug));p.addEventListener('mouseleave',()=>$('tip').hidden=true);p.addEventListener('click',()=>open(x.slug));g.append(p);x.el=p}
  $('map-legend').innerHTML=Object.entries(ST).map(([k,[l,c]])=>`<span><i class="sw" style="background:var(${c})"></i>${l}</span>`).join('');
  document.querySelectorAll('.filters button').forEach(b=>b.onclick=()=>{filter=b.dataset.f;document.querySelectorAll('.filters button').forEach(x=>x.setAttribute('aria-pressed',x===b));renderDocs()});
  $('drawer-x').onclick=()=>close();document.addEventListener('keydown',e=>{if(e.key==='Escape')close()});
  poll();setInterval(poll,2000);
}
function tip(e,slug){const x=towns[slug],s=status?.towns[slug],r=$('map').parentElement.getBoundingClientRect(),el=$('tip');el.hidden=false;el.style.left=(e.clientX-r.left)+'px';el.style.top=(e.clientY-r.top)+'px';
  el.innerHTML=`${esc(x.name)} <small>${esc(x.county)} County · ${ST[s?.status||'queued'][0]}${s?.worker?' · '+esc(s.worker):''}</small>`}
function openGis(slug){const x=towns[slug],s=status?.towns[slug]||{status:'queued'},sm=s.summary||{};
  const groups={};for(const l of s.links||[])(groups[l.kind]=groups[l.kind]||[]).push(l);
  $('drawer-body').innerHTML=`<h3>${esc(x.name)}</h3><p>${esc(x.county)} County · ${esc(x.kind)}${s.website?` · <a href="${esc(s.website)}" target="_blank" rel="noopener">town website</a>`:''}</p>
   <p><i class="sw" style="background:var(${ST[s.status][1]})"></i> ${ST[s.status][0]}${s.worker?' · '+esc(s.worker):''}${s.updated_at?' · '+fmtT(s.updated_at):''}</p>
   ${s.links?.length?`<dl><dt>Sign layers</dt><dd>${sm.sign_layers||0}${sm.sign_features?` · ${n(sm.sign_features)} signs`:''}${sm.stop_signs?` · <b>${n(sm.stop_signs)}</b> stop`:''}</dd><dt>Other layers</dt><dd>${sm.traffic_layers||0}</dd><dt>Links</dt><dd>${sm.ok_links||0} working of ${sm.links||0}</dd></dl>`:''}
   ${Object.keys(KIND).filter(k=>groups[k]).map(k=>`<p class="grp">${KIND[k]}</p><ul class="links">${groups[k].map(l=>`<li class="${l.ok?'':'bad'}"><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title||l.url)}</a>${l.ok?'':' <span class="badge">not reachable</span>'}${l.access&&l.access!=='public'?` <span class="badge">${esc(l.access)}</span>`:''}
      ${(l.layers||[]).filter(y=>y.features).map(y=>`<div class="lyr"><a href="${esc(y.url)}" target="_blank" rel="noopener">${esc(y.name)}</a> · ${n(y.features)}${y.stop_signs?` · <b>${n(y.stop_signs)} stop</b>`:''}</div>`).join('')}</li>`).join('')}</ul>`).join('')}
   ${s.notes?`<p>${esc(s.notes)}</p>`:''}`}
function open(slug){selected=slug;document.querySelectorAll('#towns path.sel').forEach(p=>p.classList.remove('sel'));towns[slug].el.classList.add('sel');
  $('drawer').hidden=false;if(GIS)return openGis(slug);
  const x=towns[slug],s=status?.towns[slug]||{status:'queued'},d=s.document||{};
  $('drawer-body').innerHTML=`<h3>${esc(x.name)}</h3><p>${esc(x.county)} County · ${esc(x.kind)}</p><p><i class="sw" style="background:var(${ST[s.status][1]})"></i> ${ST[s.status][0]}${s.worker?' · '+esc(s.worker):''}${s.updated_at?' · '+fmtT(s.updated_at):''}</p>
   ${d.url?`<dl><dt>Document</dt><dd><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.title||d.url)}</a></dd><dt>Format</dt><dd>${esc(d.format||'?')}</dd><dt>Updated</dt><dd>${esc(d.last_updated||'unknown')}</dd>
   <dt>Stop signs</dt><dd>${d.has_stop_signs?'yes':'no / unknown'}</dd><dt>Turn rules</dt><dd>${d.has_turn_prohibitions?'yes':'no / unknown'}</dd><dt>One-way</dt><dd>${d.has_one_way?'yes':'no / unknown'}</dd><dt>Verified</dt><dd>${d.verified?'opened and checked':'not opened'}</dd>${s.pipeline?`<dt>Pipeline</dt><dd>${esc(s.pipeline)}</dd>`:''}</dl>`:''}
   ${s.candidates?.length?`<p>Other leads:</p><ul>${s.candidates.map(u=>`<li><a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a></li>`).join('')}</ul>`:''}${s.notes?`<p>${esc(s.notes)}</p>`:''}`}
function close(){$('drawer').hidden=true;document.querySelectorAll('#towns path.sel').forEach(p=>p.classList.remove('sel'));selected=null}

async function poll(){
  try{const r=await fetch(R+'status.json?t='+Date.now(),{cache:'no-store'});status=await r.json();
    const age=(Date.now()-new Date(status.generated_at))/1000;$('live-dot').className=age<20?'on':'stale';$('live-text').textContent=age<20?'live':`stale ${Math.round(age)}s`;render()}
  catch(e){$('live-dot').className='';$('live-text').textContent=GIS?'offline: run python swarm.py status --kind gis':'offline: run python swarm.py status'}
}
function render(){
  const c=status.counts,total=status.total,resolved=RESOLVED.reduce((a,k)=>a+c[k],0);
  $('pct').textContent=Math.floor(100*resolved/total);
  $('bar').innerHTML=['found','partial','not_found','error','searching'].map(k=>`<i style="width:${100*c[k]/total}%;background:var(${ST[k][1]})" title="${ST[k][0]}: ${c[k]}"></i>`).join('');
  $('bar-legend').innerHTML=['found','partial','not_found','error','searching','queued'].map(k=>`<span><i class="sw" style="background:var(${ST[k][1]})"></i>${ST[k][0]} <b>${c[k]}</b></span>`).join('');
  const el=(Date.now()-new Date(status.started_at))/1000,rate=resolved>1?(resolved-1)/(el/60):0;
  $('elapsed').textContent=dur(el);$('rate').textContent=rate?`${rate.toFixed(1)}/min`:'—';$('eta').textContent=rate?dur((total-resolved)/rate*60):'—';
  for(const [slug,x] of Object.entries(towns)){const s=status.towns[slug]?.status||'queued';
    if(x.el.dataset.s!==s){x.el.setAttribute('class',s+(slug===selected?' sel':''));if(!firstPaint&&RESOLVED.includes(s)&&x.el.dataset.s)ping(x,s);x.el.dataset.s=s}}
  firstPaint=false;renderAgents();renderFeed();renderDocs();if(selected&&!$('drawer').hidden)open(selected);
}
function ping(x,s){const c=document.createElementNS('http://www.w3.org/2000/svg','circle');c.setAttribute('cx',x.cx);c.setAttribute('cy',x.cy);c.setAttribute('r',2);c.setAttribute('class','ping');
  c.style.stroke=`var(${ST[s][1]})`;$('pings').append(c);setTimeout(()=>c.remove(),2000)}
function renderAgents(){const w=Object.entries(status.workers),now=Date.now();let active=0;
  $('agents').innerHTML=w.map(([id,a])=>{const hb=a.heartbeat?(now-new Date(a.heartbeat))/1000:null;let st=a.state==='done'||a.done===a.assigned?'done':a.done||a.current?'working':'queued';
    if(st==='working'&&hb!==null&&hb>600)st='stale';if(st==='working')active++;
    const cur=a.current&&towns[a.current]?towns[a.current].name:st==='done'?'all towns resolved':st==='queued'?'waiting to launch':'between towns';
    return `<div class="agent ${st}"><div class="row"><span class="id">${esc(id.toUpperCase())}</span><span class="state">${st}</span></div><div class="cur">${st==='working'?'▸ ':''}${esc(cur)}</div>
      <div class="mini">${a.towns.map(s=>`<i class="${status.towns[s]?.status||''}" title="${esc(towns[s]?.name||s)}"></i>`).join('')}</div><div class="row"><span class="state">${a.done}/${a.assigned}</span><span class="state">${hb!==null?Math.round(hb)+'s ago':''}</span></div></div>`}).join('');
  $('agents-sub').textContent=`${active} active · ${w.length} total`}
function renderFeed(){const seen=new Set(Object.keys(prev));
  $('feed').innerHTML=status.events.length?status.events.map(e=>{const k=e.slug+e.status;return `<li class="${prev[k]?'':'new'}"><time>${fmtT(e.at)}</time><i class="dot" style="background:var(${ST[e.status]?.[1]||'--muted'})"></i><span><b>${esc(e.name)}</b> ${esc(ST[e.status]?.[0].toLowerCase()||e.status)}</span><span class="w">${esc(e.worker||'')}</span></li>`}).join(''):'<li class="empty">Waiting for the first agent report…</li>';
  prev={};for(const e of status.events)prev[e.slug+e.status]=1}
function renderDocs(){if(!status)return;const rows=Object.entries(status.towns).filter(([s,t])=>['found','partial'].includes(t.status)&&t.document?.url&&(filter==='all'||t.status===filter))
    .sort((a,b)=>(towns[a[0]]?.name||'').localeCompare(towns[b[0]]?.name||''));
  $('docs-sub').textContent=`${rows.length} shown`;
  if(GIS){const key=t=>[-(t.summary?.stop_signs||0),-(t.summary?.sign_features||0)];
    $('docs').innerHTML=rows.length?rows.sort((a,b)=>{const x=key(a[1]),y=key(b[1]);return x[0]-y[0]||x[1]-y[1]||(towns[a[0]]?.name||'').localeCompare(towns[b[0]]?.name||'')}).map(([s,t])=>{const d=t.document,sm=t.summary||{};
    return `<tr><td><a href="#" data-s="${esc(s)}">${esc(towns[s]?.name||s)}</a></td><td><a class="title" href="${esc(d.url)}" target="_blank" rel="noopener" title="${esc(d.title||d.url)}">${esc(d.title||d.url)}</a></td><td><span class="badge">${esc(KIND[d.format]||d.format||'?')}</span></td><td class="covers">${n(d.features??sm.sign_features)||'—'}</td><td class="covers">${sm.stop_signs?'<b>'+n(sm.stop_signs)+'</b>':'—'}</td><td class="covers">${esc(t.worker||'catalog')}</td></tr>`}).join(''):'<tr><td colspan="6" class="empty">No GIS links yet.</td></tr>';
    $('docs').querySelectorAll('a[data-s]').forEach(a=>a.onclick=e=>{e.preventDefault();open(a.dataset.s)});return}
  $('docs').innerHTML=rows.length?rows.map(([s,t])=>{const d=t.document,cv=[d.has_stop_signs&&'stop',d.has_turn_prohibitions&&'turn',d.has_one_way&&'1-way'].filter(Boolean);
    return `<tr><td><a href="#" data-s="${esc(s)}">${esc(towns[s]?.name||s)}</a></td><td><a class="title" href="${esc(d.url)}" target="_blank" rel="noopener" title="${esc(d.title||d.url)}">${esc(d.title||d.url)}</a></td><td><span class="badge">${esc(d.format||'?')}</span></td><td class="covers">${cv.length?'<b>'+cv.join(' · ')+'</b>':'—'}</td><td class="covers">${esc(t.worker||'')}</td></tr>`}).join(''):'<tr><td colspan="5" class="empty">No documents yet.</td></tr>';
  $('docs').querySelectorAll('a[data-s]').forEach(a=>a.onclick=e=>{e.preventDefault();open(a.dataset.s)})}
init();
