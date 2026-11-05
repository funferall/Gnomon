/* Map of regulation-derived layers (reg_harness.py / reg_ai.py outputs). Machine-made and unreviewed. */
const $=id=>document.getElementById(id), D='data/regulations/wellesley/';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const map=L.map('map').setView([42.2965,-71.2925],14);addMassGISBasemaps(map,'2025',{collapsed:true});
const COMPASS=d=>['N','NE','E','SE','S','SW','W','NW'][Math.round(((d%360)+360)%360/45)%8];
const STYLE={stop:{c:'#d0202a',shape:'oct',label:'Stop signs'},yield:{c:'#e8a317',shape:'tri',label:'Yield signs'},rtor_prohibited:{c:'#7b3fbf',shape:'sq',label:'No turn on red'},rtor_permitted:{c:'#2a9d8f',shape:'sq',label:'Turn on red permitted'}};
function shape(kind,filled,size=16){const s=STYLE[kind]||STYLE.stop,h=size/2,f=filled?s.c:'#ffffff',sw=filled?1.5:2.5,st=filled?'#ffffff':s.c;
  const pts=s.shape==='oct'?[...Array(8)].map((_,i)=>{const a=Math.PI/8+i*Math.PI/4;return `${h+h*.92*Math.cos(a)},${h+h*.92*Math.sin(a)}`}).join(' '):s.shape==='tri'?`${h},${size-1} 1,1 ${size-1},1`:`2,2 ${size-2},2 ${size-2},${size-2} 2,${size-2}`;
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><polygon points="${pts}" fill="${f}" stroke="${st}" stroke-width="${sw}"/></svg>`}
function arrowLine(coords,color,dash){const ll=coords.map(([x,y])=>[y,x]),g=L.layerGroup();L.polyline(ll,{color:'#fff',weight:7,opacity:.8}).addTo(g);L.polyline(ll,{color,weight:4,dashArray:dash}).addTo(g);
  const a=ll[ll.length-2],b=ll[ll.length-1],k=Math.cos(b[0]*Math.PI/180),dx=(b[1]-a[1])*k,dy=b[0]-a[0],n=Math.hypot(dx,dy)||1,ux=dx/n,uy=dy/n,s=0.00004;
  L.polygon([[b[0],b[1]],[b[0]-s*(uy*2.2+ux*1.1),b[1]-s*(ux*2.2-uy*1.1)/k],[b[0]-s*(uy*2.2-ux*1.1),b[1]-s*(ux*2.2+uy*1.1)/k]],{color,fillColor:color,fillOpacity:1,weight:1}).addTo(g);return g}
const groups={},counts={};
function show(html){$('detail').innerHTML='<h2>Selected</h2><div class="popup">'+html+'</div>'}
function src(p){return p.source?`<q>${esc(p.source.raw)}</q><p><a href="${D}source.pdf#page=${p.source.page}" target="_blank">Open page ${p.source.page} of the PDF</a></p>`:''}
(async()=>{
  const [signs,turns,ways,unres,extra,ffu]=await Promise.all(['regulatory_signs.geojson','turn_restrictions.geojson','one_way.geojson','unresolved.json','detected_not_in_regulations.geojson','freeform_unresolved.json'].map(f=>fetch(D+f).then(r=>r.json())));
  for(const f of signs.features){const p=f.properties,k=p.kind,found=!!p.evidence&&p.evidence!=='not_detected_in_imagery',key=k+(found?'_found':'_missing');
    (groups[key]??=L.layerGroup().addTo(map));counts[key]=(counts[key]||0)+1;const [lon,lat]=f.geometry.coordinates;
    L.marker([lat,lon],{icon:L.divIcon({className:'',html:shape(k,found),iconSize:[16,16],iconAnchor:[8,8]})}).bindTooltip(`${STYLE[k]?.label.replace(/s$/,'')||k}: ${esc(p.on_street)} at ${esc(p.at_street)}`)
     .on('click',()=>show(`<h3>${esc(STYLE[k]?.label.replace(/s$/,'')||k)}</h3><p><b>${esc(p.on_street)}</b> at <b>${esc(p.at_street)}</b>, facing ${p.travel_deg!=null?COMPASS(p.travel_deg)+'bound traffic':'—'}</p>
      <p>Enacted ${esc((p.enacted||[]).join(', ')||'n/a')} · Schedule ${esc(p.schedule)}</p><p>Placement: ${esc(p.method)}, ±${p.uncertainty95_m} m (95%)${p.calibration?`; setback ${p.calibration.setback_m} m, offset ${p.calibration.offset_m} m`:''}</p>
      <p>Imagery: ${found?`${esc(p.evidence.replaceAll('_',' '))}, ${p.evidence_distance_m} m away`:'not detected yet'}</p>${p.flags?.length?`<p>Flags: ${esc(p.flags.join(', '))}</p>`:''}${src(p)}`)).addTo(groups[key])}
  groups.turn=L.layerGroup().addTo(map);counts.turn=turns.features.length;
  for(const f of turns.features){const p=f.properties,bad=p.flags?.length;arrowLine(f.geometry.coordinates,bad?'#999':'#d0202a',bad?'6 5':null).bindTooltip(`${p.restriction.replaceAll('_',' ')}: ${esc(p.via)}`).on('click',()=>show(`<h3>${esc(p.restriction.replaceAll('_',' '))}</h3><p>From <b>${esc(p.from_street)}</b> onto <b>${esc(p.to_street)}</b> at ${esc(p.via)}</p><p>${p.time_conditions?'When: '+esc(p.time_conditions):'At all times'} · enacted ${esc(p.enacted||'n/a')}</p><p>Extracted by ${esc(p.agreeing_providers.join(', '))} (agreement)</p>${bad?`<p><b>Flag:</b> ${esc(p.flags.join(', '))}</p>`:''}<q>${esc(p.source_text)}</q>`)).addTo(groups.turn)}
  groups.oneway=L.layerGroup().addTo(map);counts.oneway=ways.features.length;
  for(const f of ways.features){const p=f.properties;arrowLine(f.geometry.coordinates,'#1f6fd1').bindTooltip(`One way: ${esc(p.street)}`).on('click',()=>show(`<h3>One-way: ${esc(p.street)}</h3><p>From ${esc(p.from)} to ${esc(p.to)}</p><p>${p.time_conditions?'When: '+esc(p.time_conditions):'At all times'} · enacted ${esc(p.enacted||'n/a')}</p><p>Direction check vs geometry: ${p.direction_check_error_deg}°</p><q>${esc(p.source_text)}</q>`)).addTo(groups.oneway)}
  groups.extra=L.layerGroup();counts.extra=extra.features.length;
  for(const f of extra.features){const [lon,lat]=f.geometry.coordinates;L.circleMarker([lat,lon],{radius:5,color:'#555',weight:2,fill:false,dashArray:'2 2'}).bindTooltip('Stop sign seen in imagery, not in the regulations').addTo(groups.extra)}
  const rows=[['stop_found',shape('stop',true),'Stop sign · regulation + imagery'],['stop_missing',shape('stop',false),'Stop sign · regulation only'],['yield_missing',shape('yield',false),'Yield sign'],['yield_found',shape('yield',true),'Yield sign · also in imagery'],
    ['rtor_prohibited_missing',shape('rtor_prohibited',false),'No turn on red'],['rtor_permitted_missing',shape('rtor_permitted',false),'Turn on red permitted'],
    ['turn','<svg width="22" height="12"><path d="M1 6h14" stroke="#d0202a" stroke-width="3"/><path d="M15 1l6 5-6 5z" fill="#d0202a"/></svg>','Prohibited turn (from → onto)'],
    ['oneway','<svg width="22" height="12"><path d="M1 6h14" stroke="#1f6fd1" stroke-width="3"/><path d="M15 1l6 5-6 5z" fill="#1f6fd1"/></svg>','One-way street (direction of travel)'],
    ['extra','<svg width="14" height="14"><circle cx="7" cy="7" r="5" fill="none" stroke="#555" stroke-width="2" stroke-dasharray="2 2"/></svg>','Seen in imagery, not in regulations']];
  $('legend').innerHTML=rows.filter(r=>counts[r[0]]).map(([k,svg,t])=>`<label class="legend-row"><input type="checkbox" data-k="${k}" ${map.hasLayer(groups[k])?'checked':''}>${svg}${t}<span class="n">${counts[k]}</span></label>`).join('');
  $('legend').querySelectorAll('input').forEach(i=>i.onchange=()=>i.checked?groups[i.dataset.k].addTo(map):groups[i.dataset.k].remove());
  const u=[...unres.map(r=>({t:r.source?.raw,why:r.reason,page:r.source?.page})),...ffu.unresolved.map(r=>({t:r.source_text,why:r.reason}))];
  $('unres-n').textContent=u.length;$('unres').innerHTML=u.map(r=>`<li>${esc(r.t)}<br><span class="muted">${esc(r.why.replaceAll('_',' '))}${r.page?` · <a href="${D}source.pdf#page=${r.page}" target="_blank">p.${r.page}</a>`:''}</span></li>`).join('');
  const b=L.latLngBounds(signs.features.map(f=>[f.geometry.coordinates[1],f.geometry.coordinates[0]]));map.fitBounds(b,{padding:[20,20]});
  const h=new URLSearchParams(location.hash.slice(1));if(h.get('z'))map.setView([+h.get('lat'),+h.get('lon')],+h.get('z'));
})();
