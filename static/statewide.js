/* Statewide map of regulation-derived stop signs (reg_statewide.py, reg_aiparse.py outputs). */
const $=id=>document.getElementById(id), D='data/regulations/';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const COMPASS=d=>['N','NE','E','SE','S','SW','W','NW'][Math.round(((d%360)+360)%360/45)%8];
const map=L.map('map',{preferCanvas:true}).setView([42.25,-71.8],8);addMassGISBasemaps(map,'basemap',{collapsed:true});
const FILL={mapped:'#1f9e89',found:'#1f9e89',partial:'#e8b23a',not_found:'#9aa5ab',queued:'#9aa5ab'};
let towns,townLayer,byslug={},signsDir=L.layerGroup().addTo(map),signsCtr=L.layerGroup().addTo(map),sel=null;
function show(h){$('detail').innerHTML='<h2>Selected</h2><div class="popup">'+h+'</div>'}
function townHtml(p){return `<h3 style="margin:0 0 4px">${esc(p.name)}</h3><p>${esc(p.county||'')} County · ${p.signs?`<b>${p.signs}</b> stop signs mapped (${p.with_direction} with direction)`:esc(({partial:'Rules found, but no stop-sign list in them',not_found:'No traffic rules found online',queued:'Not searched'})[p.status]||p.status)}</p>
  ${p.document?`<p><a href="${esc(p.document)}" target="_blank" rel="noopener">${esc(p.document_title||'Source document')}</a></p>`:''}${p.notes&&!p.signs?`<p class="muted">${esc(p.notes)}</p>`:''}`}
function selectTown(slug,zoom=true){const l=byslug[slug];if(!l)return;if(sel)townLayer.resetStyle(sel);sel=l;l.setStyle({weight:3,color:'#102e3a'});if(zoom)map.fitBounds(l.getBounds(),{padding:[20,20]});show(townHtml(l.feature.properties));
  document.querySelectorAll('#towns-list button').forEach(b=>b.classList.toggle('sel',b.dataset.s===slug))}
function list(){const q=$('q').value.toLowerCase();const fs=towns.features.filter(f=>f.properties.name.toLowerCase().includes(q)).sort((a,b)=>b.properties.signs-a.properties.signs||a.properties.name.localeCompare(b.properties.name));
  $('towns-list').innerHTML=fs.map(f=>`<button data-s="${esc(f.properties.slug)}"><span><i class="sw" style="background:${FILL[f.properties.status]};width:9px;height:9px;margin-right:6px"></i>${esc(f.properties.name)}</span><span class="n">${f.properties.signs||''}</span></button>`).join('');
  $('towns-list').querySelectorAll('button').forEach(b=>b.onclick=()=>selectTown(b.dataset.s))}
(async()=>{
  const [t,s]=await Promise.all([fetch(D+'statewide_towns.geojson').then(r=>r.json()),fetch(D+'statewide_stop_signs.geojson').then(r=>r.json())]);towns=t;
  townLayer=L.geoJSON(t,{style:f=>({color:'#ffffff',weight:.6,fillColor:FILL[f.properties.status],fillOpacity:f.properties.signs?.28:.18}),
    onEachFeature:(f,l)=>{byslug[f.properties.slug]=l;l.bindTooltip(`${f.properties.name}${f.properties.signs?` · ${f.properties.signs} signs`:''}`,{sticky:true});l.on('click',()=>selectTown(f.properties.slug,false))}}).addTo(map);
  for(const f of s.features){const p=f.properties,[lon,lat]=f.geometry.coordinates,dir=p.method==='deterministic_approach_offset';
    L.circleMarker([lat,lon],dir?{radius:3.5,weight:1,color:'#fff',fillColor:'#d0202a',fillOpacity:.95}:{radius:3.5,weight:1.6,color:'#e07b00',fill:false})
     .on('click',e=>{L.DomEvent.stop(e);show(`<h3 style="margin:0 0 4px">Stop sign · ${esc(p.town)}</h3><p><b>${esc(p.on_street)}</b> at <b>${esc(p.at_street)}</b>${p.travel_deg!=null?`, facing ${COMPASS(p.travel_deg)}bound traffic`:''}</p>
       <p>${dir?`Placed on the approach (±${p.uncertainty95_m} m)`:`Direction not stated: placed at the intersection (±${p.uncertainty95_m} m)`}</p>${(p.flags||[]).length?`<p class="muted">Flags: ${esc(p.flags.join(', '))}</p>`:''}
       ${p.source?.raw?`<q>${esc(p.source.raw)}</q>`:''}${p.source?.url?`<p><a href="${esc(p.source.url)}" target="_blank" rel="noopener">Source document</a></p>`:''}`)}).addTo(dir?signsDir:signsCtr)}
  const mapped=t.features.filter(f=>f.properties.signs);$('s-towns').textContent=mapped.length;$('s-signs').textContent=s.features.length.toLocaleString();
  $('s-dir').textContent=Math.round(100*s.features.filter(f=>f.properties.method==='deterministic_approach_offset').length/s.features.length)+'%';
  list();$('q').oninput=list;$('show-signs').onchange=e=>e.target.checked?signsDir.addTo(map):signsDir.remove();$('show-centre').onchange=e=>e.target.checked?signsCtr.addTo(map):signsCtr.remove();
  map.fitBounds(townLayer.getBounds(),{padding:[10,10]});
})();
