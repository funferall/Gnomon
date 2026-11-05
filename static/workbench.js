/* Gnomon workbench: map + image + review in one keyboard-first surface. Talks to review_server.py. */
'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// ------------------------------------------------------------------ configuration
const CLASS_COLORS = {'stop sign':'#c0245c','speed limit sign':'#6b4fc8','one way sign':'#14a3a3','street name sign':'#2a7fd4','traffic sign':'#e7a21c',
  'fire hydrant':'#e0302b','traffic light':'#1f8a4c','bollard':'#8a6d4d','storm drain':'#5d8aa8','manhole cover':'#56636b','unknown':'#888'};
const ROLE_FOR = {'stop sign':'intersection_control','speed limit sign':'speed_limit','one way sign':'one_way','street name sign':'street_name','traffic light':'intersection_control',
  'fire hydrant':'infrastructure','storm drain':'infrastructure','manhole cover':'infrastructure','bollard':'access_restriction','traffic sign':'unknown'};
const VIEW_ORDER = ['front','right','back','left','up','down','flat'];
const ACTIONS = [
  ['accept','Accept','a'],['reject','Reject','r'],['uncertain','Unsure','u'],['duplicate','Duplicate of a placed asset','d'],
  ['save','Save & next','Enter'],['skip','Skip to next in queue','n'],['prevItem','Previous queue item','b'],['undo','Undo last save','Ctrl+z'],
  ['useEstimate','Use estimated position','e'],['place','Place on map','p'],['clearPos','Clear position','Shift+p'],
  ['nextDet','Next detection in view',']'],['prevDet','Previous detection in view','['],
  ['nextImage','Next image in sequence','ArrowRight'],['prevImage','Previous image in sequence','ArrowLeft'],
  ['nextView','Next panorama view','v'],['prevView','Previous panorama view','Shift+v'],
  ['zoomFit','Fit / zoom to detection','f'],['centerMap','Center map on camera','c'],['streetView','Open Google Street View','g'],['ocr','Read sign text (local OCR)','t'],
  ['queueList','Show queue list','q'],['help','Shortcuts','?'],['settings','Settings',','],
];
const DEFAULTS = {theme:'system',defaultUnc:1.5,quick:false,zoomToBox:true,follow:true,basemap:'MassGIS imagery · 2025',markerSize:5,
  layers:{cameras:true,estMulti:true,estSingle:false,placed:true,rays:true},colors:{},hotkeys:{},split:45};
let S = loadSettings();
function loadSettings(){try{const s=JSON.parse(localStorage.getItem('gnomon-settings')||'{}');return {...DEFAULTS,...s,layers:{...DEFAULTS.layers,...(s.layers||{})}}}catch(e){return structuredClone(DEFAULTS)}}
function persist(){try{localStorage.setItem('gnomon-settings',JSON.stringify(S))}catch(e){}}
const color = c => S.colors[c] || CLASS_COLORS[c] || CLASS_COLORS.unknown;

// ------------------------------------------------------------------ hotkeys
let LABELS = [];
function classActions(){return LABELS.map((l,i)=>['class'+i,'Class: '+l,String((i+1)%10)])}
function allActions(){return [...ACTIONS,...classActions()]}
function keyFor(id){const d=allActions().find(a=>a[0]===id);return id in S.hotkeys?S.hotkeys[id]:(d?d[2]:'')}
function combo(e){const mods=[];if(e.ctrlKey||e.metaKey)mods.push('Ctrl');if(e.altKey)mods.push('Alt');let k=e.key;
  if(k.length===1){if(/[a-z]/i.test(k)){if(e.shiftKey)mods.push('Shift');k=k.toLowerCase()}else if(k===' ')k='Space'}else if(e.shiftKey&&!['Shift','Control','Alt','Meta'].includes(k))mods.push('Shift');
  return [...mods,k].join('+')}
function pretty(k){if(!k)return '';return k.split('+').map(p=>({ArrowLeft:'←',ArrowRight:'→',ArrowUp:'↑',ArrowDown:'↓',Enter:'Enter',Escape:'Esc',Space:'Space'}[p]||(p.length===1?p.toUpperCase():p))).join('+')}
let keymap = new Map();
function rebuildKeymap(){keymap=new Map();for(const [id] of allActions()){const k=keyFor(id);if(k)keymap.set(k,id)}
  document.querySelectorAll('kbd[data-hint]').forEach(el=>el.textContent=pretty(keyFor(el.dataset.hint)));renderClassKeys()}
function renderClassKeys(){$('classkeys').innerHTML=LABELS.map((l,i)=>{const k=keyFor('class'+i);return k?`<span><kbd>${esc(pretty(k))}</kbd>${esc(l)}</span>`:''}).join('')}

// ------------------------------------------------------------------ state
let session=null;
const Q={items:[],offset:0,total:0,index:-1,limit:60};
let img=null;        // current image + view: {provider,image_id,view,views,view_file,detections,captured,rights,camera:[lon,lat]}
let cur=null;        // current observation detail
let fromQueue=false, dirty=false, decision=null, lastSaved=null, mode=null; // mode: 'place' | 'pick-duplicate'
let loadSeq=0;

async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Review-Token':session.token}:{},body:body?JSON.stringify(body):undefined});
  let j={};try{j=await r.json()}catch(e){}if(!r.ok)throw Object.assign(Error(j.error||`Request failed (${r.status})`),{status:r.status});return j}
function status(text,kind=''){const el=$('status');el.textContent=text||'';el.className='status '+kind}
function confirmLeave(){return !dirty||confirm('Discard unsaved changes to this detection?')}
function setDirty(){if(cur){dirty=true;status('Unsaved changes')}}

// ------------------------------------------------------------------ map
const map=L.map('map',{preferCanvas:true,zoomControl:true}).setView([42.296,-71.29],14);
const basemaps=addMassGISBasemaps(map,S.basemap,{collapsed:true});
map.on('baselayerchange',e=>{S.basemap=e.name;persist()});
const layers={cameras:L.markerClusterGroup({disableClusteringAtZoom:17,showCoverageOnHover:false,chunkedLoading:true,maxClusterRadius:50,
  iconCreateFunction:c=>{const n=c.getChildCount(),s=n<100?28:n<1000?34:40;return L.divIcon({html:n.toLocaleString(),className:'cam-cluster',iconSize:[s,s]})}}),
  estMulti:L.layerGroup(),estSingle:L.layerGroup(),placed:L.layerGroup(),selection:L.layerGroup()};
let cameraData=[],estimateData=[],placedData=null,posMarker=null;
function applyLayerVisibility(){for(const k of ['cameras','estMulti','estSingle','placed']){S.layers[k]?layers[k].addTo(map):layers[k].remove()}layers.selection.addTo(map)}
function camLatLng(provider,id,lon,lat){const p=CameraPositions.coordinate(provider,id,[lon,lat]);return [p[1],p[0]]}
function drawCameras(){layers.cameras.clearLayers();const ms=cameraData.map(([provider,id,lon,lat,n,r])=>L.circleMarker(camLatLng(provider,id,lon,lat),
  {radius:Math.max(3,S.markerSize-1),weight:1,color:'#fff',fillColor:r>=n?'#7c8b90':'#1d6f8a',fillOpacity:.9}).bindTooltip(`${n} detection${n>1?'s':''} · ${r} reviewed`).on('click',()=>{if(confirmLeave())openImage(provider,id,null,0,true)}));
  layers.cameras.addLayers(ms)}
function drawEstimates(){layers.estMulti.clearLayers();layers.estSingle.clearLayers();for(const [id,cls,state,lon,lat,u95,n,oid] of estimateData){const multi=state==='multi_view_estimate';
  L.circleMarker([lat,lon],{radius:multi?S.markerSize:S.markerSize-1.5,weight:multi?1.5:1,color:multi?'#fff':color(cls),fillColor:color(cls),fillOpacity:multi?.9:.4})
   .bindTooltip(`${cls} · estimate ±${u95.toFixed(1)} m · ${n} view${n>1?'s':''}`).on('click',()=>{if(oid&&confirmLeave())loadObservation(oid,false)}).addTo(multi?layers.estMulti:layers.estSingle)}}
function drawPlaced(){layers.placed.clearLayers();if(!placedData)return;for(const f of placedData.features){const [lon,lat]=f.geometry.coordinates,p=f.properties;
  L.circleMarker([lat,lon],{radius:S.markerSize+2,weight:3,color:'#111',fillColor:color(p.class),fillOpacity:1}).bindTooltip(`Placed ${p.class} · ${p.id} · ±${p.uncertainty_m} m`)
   .on('click',e=>{L.DomEvent.stop(e);if(mode==='pick-duplicate'){$('f-asset').value=p.id;setMode(null);setDirty();status('Linked as duplicate of '+p.id)}}).addTo(layers.placed)}}
async function loadMapData(){const [c,e,a]=await Promise.allSettled([api('/api/cameras'),api('/api/estimates'),api('/api/assets')]);
  if(c.status==='fulfilled'){cameraData=c.value.cameras;drawCameras()}if(e.status==='fulfilled'){estimateData=e.value.estimates;drawEstimates()}if(a.status==='fulfilled'){placedData=a.value;drawPlaced()}}
function ellipse(lat,lon,e){const out=[],t=e.major_axis_azimuth_deg*Math.PI/180,a=e.semi_major95_m,b=e.semi_minor95_m,k=111320,kl=k*Math.cos(lat*Math.PI/180);
  for(let i=0;i<=40;i++){const p=i/40*2*Math.PI,de=Math.sin(t)*a*Math.cos(p)+Math.cos(t)*b*Math.sin(p),dn=Math.cos(t)*a*Math.cos(p)-Math.sin(t)*b*Math.sin(p);out.push([lat+dn/k,lon+de/kl])}return out}
function drawSelection(){layers.selection.clearLayers();if(!img)return;const cam=cameraFor();
  if(cur&&S.layers.rays){const e=cur.estimate,g=cur.geometry;
    if(e){for(const [lon,lat] of e.cameras)L.polyline([[lat,lon],[e.lat,e.lon]],{color:'#ffd84a',weight:1.5,opacity:.85,interactive:false}).addTo(layers.selection);
      L.polygon(ellipse(e.lat,e.lon,e.ellipse),{color:color(cur.label),weight:1.5,fillOpacity:.1,dashArray:'4 3',interactive:false}).addTo(layers.selection);
      L.circleMarker([e.lat,e.lon],{radius:S.markerSize+1,color:'#fff',weight:2,fillColor:color(cur.label),fillOpacity:1,interactive:false}).bindTooltip('Machine estimate').addTo(layers.selection)}
    else if(g){const r=g.range_m||25,a=g.azimuth_deg*Math.PI/180,k=111320,end=[cam[0]+Math.cos(a)*r/k,cam[1]+Math.sin(a)*r/(k*Math.cos(cam[0]*Math.PI/180))];
      L.polyline([cam,end],{color:'#ffd84a',weight:2,dashArray:g.range_m?null:'5 5',interactive:false}).addTo(layers.selection)}}
  L.circleMarker(cam,{radius:6,color:'#fff',weight:2,fillColor:'#126b86',fillOpacity:1,interactive:false}).addTo(layers.selection)}
function cameraFor(){if(!img)return null;return camLatLng(img.provider,img.image_id,img.camera[0],img.camera[1])}
function setPosition(lat,lon,changed=true){$('f-lat').value=lat==null?'':lat.toFixed(7);$('f-lon').value=lon==null?'':lon.toFixed(7);
  if(posMarker){posMarker.remove();posMarker=null}
  if(lat!=null){posMarker=L.marker([lat,lon],{draggable:true,keyboard:false,zIndexOffset:1000,icon:L.divIcon({className:'',html:'<svg width="22" height="22" viewBox="0 0 22 22"><circle cx="11" cy="11" r="7" fill="none" stroke="#fff" stroke-width="4"/><circle cx="11" cy="11" r="7" fill="none" stroke="#e8642c" stroke-width="2.5"/><circle cx="11" cy="11" r="1.6" fill="#e8642c"/></svg>',iconSize:[22,22],iconAnchor:[11,11]})})
    .bindTooltip('Asset position · drag to adjust').addTo(map);posMarker.on('dragend',()=>{const p=posMarker.getLatLng();$('f-lat').value=p.lat.toFixed(7);$('f-lon').value=p.lng.toFixed(7);setDirty()})}
  if(changed)setDirty()}
function setMode(m){mode=m;$('place').setAttribute('aria-pressed',m==='place');const hud=$('map-hud');
  hud.hidden=!m;hud.classList.toggle('active',!!m);hud.textContent=m==='place'?'Click the asset’s physical location. Esc cancels.':m==='pick-duplicate'?'Click the placed asset (dark ring) this detection duplicates. Esc cancels.':'';
  map.getContainer().style.cursor=m?'crosshair':''}
map.on('click',e=>{if(mode==='place'){setPosition(e.latlng.lat,e.latlng.lng);if(!$('f-unc').value)$('f-unc').value=S.defaultUnc;setMode(null)}});

// ------------------------------------------------------------------ image stage (fit, zoom, pan)
const stage=$('stage'),frame=$('frame'),photo=$('photo');
const T={s:1,x:0,y:0,fit:1};
function applyT(animate=false){frame.classList.toggle('animate',animate);frame.style.transform=`translate(${T.x}px,${T.y}px) scale(${T.s})`}
function fitImage(animate=false){if(!photo.naturalWidth)return;const w=stage.clientWidth,h=stage.clientHeight;T.fit=Math.min(w/photo.naturalWidth,h/photo.naturalHeight);T.s=T.fit;
  T.x=(w-photo.naturalWidth*T.s)/2;T.y=(h-photo.naturalHeight*T.s)/2;applyT(animate)}
function zoomToBox(animate=true){if(!cur||!photo.naturalWidth)return fitImage(animate);const b=cur.box,[x0,y0,x1,y1]=b.xyxy,sx=photo.naturalWidth/b.width,sy=photo.naturalHeight/b.height;
  const w=stage.clientWidth,h=stage.clientHeight,bw=(x1-x0)*sx,bh=(y1-y0)*sy;let s=Math.min(w*.4/bw,h*.4/bh);s=Math.max(T.fit,Math.min(s,T.fit*3));
  T.s=s;T.x=w/2-((x0+x1)/2*sx)*s;T.y=h/2-((y0+y1)/2*sy)*s;applyT(animate)}
let boxZoom=false; // true while the image is zoomed to the selected detection
stage.addEventListener('wheel',e=>{if(!photo.naturalWidth)return;e.preventDefault();const r=stage.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const ns=Math.max(T.fit*.9,Math.min(T.fit*12,T.s*Math.exp(-e.deltaY*.0015)));T.x=mx-(mx-T.x)*ns/T.s;T.y=my-(my-T.y)*ns/T.s;T.s=ns;applyT();boxZoom=false},{passive:false});
let pan=null;
stage.addEventListener('pointerdown',e=>{if(e.target.closest('.box')||e.button!==0)return;pan={x:e.clientX,y:e.clientY,tx:T.x,ty:T.y};stage.setPointerCapture(e.pointerId);stage.classList.add('panning')});
stage.addEventListener('pointermove',e=>{if(!pan)return;T.x=pan.tx+e.clientX-pan.x;T.y=pan.ty+e.clientY-pan.y;applyT()});
stage.addEventListener('pointerup',()=>{pan=null;stage.classList.remove('panning')});
stage.addEventListener('dblclick',e=>{if(!e.target.closest('.box')){fitImage(true);boxZoom=false}});
new ResizeObserver(()=>{if(!photo.naturalWidth)return;boxZoom&&cur?zoomToBox(false):fitImage()}).observe(stage);
function showPhoto(src,seq){return new Promise(res=>{if(photo.getAttribute('src')===src&&photo.complete&&photo.naturalWidth){res(true);return}
  $('stage-message').textContent='Loading image…';$('stage-message').hidden=false;frame.style.visibility='hidden';
  photo.onload=()=>{if(seq!==loadSeq)return res(false);frame.style.width=photo.naturalWidth+'px';frame.style.height=photo.naturalHeight+'px';frame.style.visibility='';$('stage-message').hidden=true;fitImage();res(true)};
  photo.onerror=()=>{if(seq!==loadSeq)return res(false);$('stage-message').textContent='Image unavailable. Open the source link to inspect it.';res(false)};photo.src=src})}
function drawBoxes(){const box=$('boxes');box.replaceChildren();if(!img)return;for(const d of img.detections){const b=d.box,[x0,y0,x1,y1]=b.xyxy,el=document.createElement('button');
  el.type='button';el.className='box'+(d.decision?' reviewed':'')+(cur&&cur.id===d.id?' selected':'');el.setAttribute('aria-label',`${d.human_label||d.label} ${Math.round(d.score*100)}%`);
  el.title=`${d.human_label||d.label} · ${Math.round(d.score*100)}%${d.decision?' · '+d.decision:''}`;
  Object.assign(el.style,{left:100*x0/b.width+'%',top:100*y0/b.height+'%',width:100*(x1-x0)/b.width+'%',height:100*(y1-y0)/b.height+'%'});
  el.onclick=e=>{e.stopPropagation();if(cur?.id!==d.id&&confirmLeave())loadObservation(d.id,false)};box.append(el)}}

// ------------------------------------------------------------------ image + view navigation
function renderViews(){const seg=$('views');seg.replaceChildren();if(!img)return;const views=VIEW_ORDER.filter(v=>img.views.includes(v));
  for(const v of views){const b=document.createElement('button');b.type='button';b.textContent=v;b.setAttribute('aria-pressed',v===img.view);b.onclick=()=>{if(v!==img.view&&confirmLeave())openImage(img.provider,img.image_id,v,0,true)};seg.append(b)}}
function renderImageMeta(){if(!img)return;const when=img.captured?new Date(img.captured).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'}):'date unknown';
  const creator=img.rights?.creator;const who=creator&&typeof creator==='object'?(creator.username||creator.id):creator||'';
  $('image-meta').textContent=`${when}${who?' · '+who:''} · ${img.provider} ${img.image_id}`;$('source').href=img.rights?.source_url||'#';$('source').setAttribute('aria-disabled',!img.rights?.source_url)}
async function openImage(provider,image_id,view,direction=0,selectFirst=false){const seq=++loadSeq;
  try{const d=await api('/api/image-neighbor?'+new URLSearchParams({provider,image_id,direction,view:view||img?.view||'front',order:'sequence'}));
    if(seq!==loadSeq)return;if(d.end){status('End of this sequence in that direction.');return}
    img={provider:d.image.provider,image_id:d.image.image_id,view:d.view_name,views:d.views,view_file:d.view_file,detections:d.observations,captured:d.image.captured,rights:d.image.rights,camera:[d.image.camera_lon,d.image.camera_lat]};
    renderViews();renderImageMeta();if(d.sequence_fallback)status('Sequence ended; continued in town chronology.');
    const ok=await showPhoto(d.view_file,seq);if(seq!==loadSeq)return;
    const keep=cur&&img.detections.some(x=>x.id===cur.id);
    if(!keep){const qid=Q.items[Q.index]?.id;if(qid&&img.detections.some(x=>x.id===qid))return loadObservation(qid,true); // back on the queue item's view
      cur=null;fromQueue=false;if(selectFirst&&img.detections.length){const first=img.detections.find(x=>!x.decision)||img.detections[0];return loadObservation(first.id,false)}renderInspector()}
    drawBoxes();renderDetections();drawSelection();updateStreetView();followCamera();if(ok&&!cur)fitImage(true)}
  catch(e){status(e.message,'error')}}
function stepView(dir){if(!img)return;const vs=VIEW_ORDER.filter(v=>img.views.includes(v));if(vs.length<2)return;const i=vs.indexOf(img.view);if(confirmLeave())openImage(img.provider,img.image_id,vs[(i+dir+vs.length)%vs.length],0,true)}
function followCamera(){if(!S.follow||!img)return;const c=cameraFor();if(map.getZoom()<17)map.setView(c,18,{animate:false});else if(!map.getBounds().pad(-.2).contains(c))map.panTo(c)}

// ------------------------------------------------------------------ observation + inspector
async function loadObservation(id,viaQueue){const seq=++loadSeq;status('Loading…');
  try{const o=await api('/api/observation?id='+encodeURIComponent(id));if(seq!==loadSeq)return;
    const view=o.box.view||'flat';
    if(!img||img.provider!==o.provider||img.image_id!==o.image_id||img.view!==view){const d=await api('/api/image-neighbor?'+new URLSearchParams({provider:o.provider,image_id:o.image_id,direction:0,view,order:'sequence'}));if(seq!==loadSeq)return;
      img={provider:d.image.provider,image_id:d.image.image_id,view:d.view_name,views:d.views,view_file:d.view_file,detections:d.observations,captured:d.image.captured,rights:d.image.rights,camera:[d.image.camera_lon,d.image.camera_lat]};renderViews();renderImageMeta()}
    cur=o;fromQueue=!!viaQueue;dirty=false;setMode(null);renderQueue();
    const ok=await showPhoto(img.view_file,seq);if(seq!==loadSeq)return;
    fillForm();renderInspector();drawBoxes();renderDetections();drawSelection();updateStreetView();followCamera();
    if(ok){boxZoom=S.zoomToBox;boxZoom?zoomToBox(false):fitImage()}
    status(cur.human?`Reviewed by ${cur.human.reviewer} · ${cur.human.decision}`:'')}
  catch(e){status(e.message,'error')}}
function fillForm(){const h=cur.human||{};setDecision(h.decision||null,false);const label=h.label||cur.label;$('f-label').value=label;$('f-role').value=h.routing_role||ROLE_FOR[label]||'unknown';
  $('f-text').value=h.text||'';$('f-unc').value=h.uncertainty_m??'';$('f-asset').value=h.asset_id&&h.decision==='duplicate'?h.asset_id:'';$('f-notes').value=h.notes||'';$('f-vis').value=h.visibility||'unknown';$('f-occ').value=h.occlusion||'unknown';
  setPosition(h.lat??null,h.lon??null,false)}
function renderInspector(){const has=!!cur;$('editor').hidden=!has;$('inspector-empty').hidden=has;$('save').disabled=!has;$('skip').disabled=!has&&!Q.items.length;$('undo').disabled=!lastSaved;
  if(!has){setPosition(null,null,false);return}
  $('crop').src=cur.crop;$('subject-title').textContent=cur.label;
  $('subject-meta').textContent=`Detector ${Math.round(cur.score*100)}% · ${cur.box.view||'flat'} view${fromQueue?` · queue ${Q.offset+Q.index+1} of ${Q.total.toLocaleString()}`:''}`;
  const ai=cur.ai?.response;$('ai-line').textContent=ai?`AI check: ${ai.decision} · ${ai.correct_class}${ai.visible_text?` · “${ai.visible_text}”`:''}`:'';$('ai-line').hidden=!ai;
  const e=cur.estimate,g=cur.geometry;let line='No machine position for this detection.';
  if(e)line=`Estimated ${g?.range_m?g.range_m.toFixed(1)+' m from camera, ':''}±${e.uncertainty95_m.toFixed(1)} m · ${e.state==='multi_view_estimate'?`triangulated from ${e.n_observations} views`:'single view'}`;
  else if(g&&g.range_m)line=`Single-view range ${g.range_m.toFixed(1)} m · bearing ${g.azimuth_deg.toFixed(0)}°`;
  else if(g)line=`Bearing ${g.azimuth_deg.toFixed(0)}° only; distance unknown. Place it on the map.`;
  $('estimate-line').textContent=line;$('use-estimate').disabled=!(e||g?.position);
  $('dup-row').hidden=decision!=='duplicate';$('ocr').disabled=!/sign/.test($('f-label').value)}
function renderDetections(){const box=$('detections');box.replaceChildren();if(!img)return;
  if(!img.detections.length){const p=document.createElement('p');p.className='meta';p.textContent='No detections in this view. Try another view or image.';box.append(p);return}
  for(const d of img.detections){const b=document.createElement('button');b.type='button';b.className='det';b.setAttribute('role','option');b.setAttribute('aria-selected',cur?.id===d.id);
    const label=d.human_label||d.label;b.innerHTML=`<span class="dot" style="background:${color(label)}"></span>${esc(label)} <span class="meta">${Math.round(d.score*100)}%</span><span class="st ${esc(d.decision||'')}" title="${esc(d.decision||'unreviewed')}"></span>`;
    b.onclick=()=>{if(cur?.id!==d.id&&confirmLeave())loadObservation(d.id,false)};box.append(b)}}
function setDecision(d,changed=true){decision=d;document.querySelectorAll('.decision button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.decision===d));
  $('dup-row').hidden=d!=='duplicate';if(changed)setDirty()}
function setLabel(label){const prev=$('f-label').value;$('f-label').value=label;if($('f-role').value===(ROLE_FOR[prev]||'unknown'))$('f-role').value=ROLE_FOR[label]||'unknown';$('ocr').disabled=!/sign/.test(label);setDirty()}
function useEstimate(){if(!cur)return;const e=cur.estimate,g=cur.geometry;
  if(e){setPosition(e.lat,e.lon);$('f-unc').value=e.uncertainty95_m.toFixed(1)}
  else if(g?.position){setPosition(g.position[1],g.position[0]);$('f-unc').value=Math.max(4.4,2.45*Math.hypot(1.8,(g.range_m||0)*(g.range_sigma_log||.3))).toFixed(1)}
  else return status('No machine position to use; press '+pretty(keyFor('place'))+' to place it.','error');
  status('Machine estimate copied. Check it against the aerial and drag to adjust.')}
function updateStreetView(){const a=$('streetview');if(!img){a.setAttribute('aria-disabled','true');return}
  const g=cur?.geometry,c=g?.camera||img.camera,p=new URLSearchParams({api:'1',map_action:'pano',viewpoint:`${c[1].toFixed(6)},${c[0].toFixed(6)}`});
  if(g){p.set('heading',g.azimuth_deg.toFixed(0));p.set('pitch',Math.max(-30,Math.min(30,g.elevation_deg||0)).toFixed(0))}p.set('fov','70');
  a.href='https://www.google.com/maps/@?'+p.toString();a.setAttribute('aria-disabled','false');a.title=g?'Google Street View at this camera, facing the object':'Google Street View at this camera'}

// ------------------------------------------------------------------ queue
function queueParams(){return {label:$('q-class').value,status:$('q-status').value,sort:$('q-sort').value,search:$('q-search').value,offset:Q.offset,limit:Q.limit}}
async function loadQueue(selectIndex=0,select=true){try{const r=await api('/api/queue?'+new URLSearchParams(queueParams()));Q.items=r.items;Q.total=r.total;Q.index=-1;renderQueue();
    if(!select)return;if(Q.items.length){await selectQueue(Math.min(selectIndex,Q.items.length-1))}else{$('q-pos').textContent='0 / 0';if(!img)$('stage-message').textContent='Queue is empty for these filters. Change the filters or click a camera on the map.';renderInspector()}}
  catch(e){status(e.message,'error')}}
function renderQueue(){$('q-pos').textContent=Q.total?`${Q.index<0||!fromQueue&&cur?'–':(Q.offset+Q.index+1).toLocaleString()} / ${Q.total.toLocaleString()}`:'0 / 0';
  $('q-prev').disabled=Q.offset+Q.index<=0;$('q-next').disabled=Q.offset+Q.index+1>=Q.total;$('q-page-prev').disabled=Q.offset===0;$('q-page-next').disabled=Q.offset+Q.items.length>=Q.total;
  if($('queue-panel').hidden)return;const list=$('queue-list');list.replaceChildren();Q.items.forEach((it,i)=>{const b=document.createElement('button');b.type='button';b.className='q-item';b.setAttribute('role','option');b.setAttribute('aria-selected',i===Q.index);
    b.innerHTML=`<img src="${esc(it.crop)}" alt="" loading="lazy"><span>${esc(it.label)}<small>${Math.round(it.score*100)}% · ${esc(it.decision||'unreviewed')}</small></span>`;b.onclick=()=>{if(confirmLeave()){selectQueue(i);toggleQueueList(false)}};list.append(b)});
  list.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'})}
async function selectQueue(i){if(i<0||i>=Q.items.length)return;Q.index=i;renderQueue();await loadObservation(Q.items[i].id,true)}
async function stepQueue(dir){const target=Q.index+dir;if(target>=0&&target<Q.items.length)return selectQueue(target);
  if(dir>0&&Q.offset+Q.items.length<Q.total){Q.offset+=Q.items.length;return loadQueue(0)}
  if(dir<0&&Q.offset>0){Q.offset=Math.max(0,Q.offset-Q.limit);return loadQueue(Q.limit-1)}
  status(dir>0?'End of the queue. Change filters or refresh.':'Start of the queue.')}
function toggleQueueList(force){const p=$('queue-panel'),show=force??p.hidden;p.hidden=!show;$('q-list-toggle').setAttribute('aria-expanded',show);if(show)renderQueue()}

// ------------------------------------------------------------------ save / skip / undo
function payload(){const lat=$('f-lat').value,lon=$('f-lon').value;let unc=$('f-unc').value;if(lat&&!unc)unc=S.defaultUnc;
  return {id:cur.id,revision:cur.human?.revision||0,decision,label:$('f-label').value,routing_role:$('f-role').value,text:$('f-text').value,lat:lat||null,lon:lon||null,uncertainty_m:lat?unc:null,
    distance_m:null,distance_basis:'',visibility:$('f-vis').value,occlusion:$('f-occ').value,asset_id:$('f-asset').value,notes:$('f-notes').value,reviewer:$('reviewer').value.trim()}}
let saving=false;
async function save(){if(!cur||saving)return;if(!$('reviewer').value.trim()){$('reviewer').focus();return status('Enter your reviewer initials (top right) before saving.','error')}
  if(!decision)return status(`Choose a decision first: ${['accept','reject','uncertain','duplicate'].map(a=>pretty(keyFor(a))).join(' / ')}.`,'error');
  saving=true;$('save').disabled=true;status('Saving…');
  try{const r=await api('/api/review',payload());lastSaved={id:cur.id,revision:r.revision};dirty=false;
    const d=img?.detections.find(x=>x.id===cur.id);if(d){d.decision=r.decision;d.human_label=r.label}const qi=Q.items.find(x=>x.id===cur.id);if(qi)qi.decision=r.decision;
    if(r.decision==='accept'&&r.lat!=null)api('/api/assets').then(a=>{placedData=a;drawPlaced()}).catch(()=>{});refreshStats();
    status(`Saved ${r.decision} · ${r.label}`,'ok');await advance()}
  catch(e){status(e.status===409?e.message+' Press '+pretty(keyFor('skip'))+' to move on or reload.':e.message,'error')}finally{saving=false;$('save').disabled=!cur;$('undo').disabled=!lastSaved}}
async function advance(){if(fromQueue)return stepQueue(1);const next=img?.detections.find(x=>!x.decision&&x.id!==cur?.id);if(next)return loadObservation(next.id,false);
  drawBoxes();renderDetections();status('All detections in this view are reviewed. Use '+pretty(keyFor('nextImage'))+' for the next image or '+pretty(keyFor('skip'))+' for the queue.','ok')}
async function skip(){if(!confirmLeave())return;dirty=false;return stepQueue(1)}
async function undo(){if(!lastSaved)return;try{await api('/api/undo',lastSaved);const id=lastSaved.id;lastSaved=null;dirty=false;status('Last save undone.','ok');refreshStats();
    api('/api/assets').then(a=>{placedData=a;drawPlaced()}).catch(()=>{});const qi=Q.items.findIndex(x=>x.id===id);if(qi>=0){Q.items[qi].decision=null;Q.index=qi;renderQueue()}await loadObservation(id,qi>=0)}
  catch(e){status(e.message,'error')}}
async function refreshStats(){try{const s=await api('/api/stats'),reviewed=Object.values(s.reviews).reduce((a,b)=>a+b,0);
  $('stats').textContent=`${(s.images.scanned||0).toLocaleString()} images scanned · ${s.observations.toLocaleString()} detections · ${reviewed.toLocaleString()} reviewed · ${s.placed_assets.toLocaleString()} placed`}catch(e){$('stats').textContent='Server unavailable: run python review_server.py'}}

async function ocr(){if(!cur||!photo.naturalWidth)return;const b=cur.box,[x0,y0,x1,y1]=b.xyxy,sx=photo.naturalWidth/b.width,sy=photo.naturalHeight/b.height,px=(x1-x0)*.15,py=(y1-y0)*.15;
  const x=Math.max(0,(x0-px)*sx),y=Math.max(0,(y0-py)*sy),w=Math.min(photo.naturalWidth-x,(x1-x0+2*px)*sx),h=Math.min(photo.naturalHeight-y,(y1-y0+2*py)*sy),scale=Math.min(4,Math.max(1,600/w));
  const c=document.createElement('canvas');c.width=Math.round(w*scale);c.height=Math.round(h*scale);c.getContext('2d').drawImage(photo,x,y,w,h,0,0,c.width,c.height);
  const id=cur.id;status(`Reading text with ${VisionOCR.model()}…`);try{const r=await VisionOCR.recognize(c,photo);if(cur?.id!==id)return;if(r.text){$('f-text').value=r.text;setDirty();status('Text read locally. Check it against the crop.','ok')}else status('No legible text found.')}
  catch(e){status('OCR unavailable: '+(e.message||'is Ollama running?'),'error')}}

// ------------------------------------------------------------------ actions + keyboard
const run={accept:()=>pickDecision('accept'),reject:()=>pickDecision('reject'),uncertain:()=>pickDecision('uncertain'),duplicate:()=>pickDecision('duplicate'),
  save,skip,prevItem:()=>{if(confirmLeave()){dirty=false;stepQueue(-1)}},undo,useEstimate,place:()=>{if(cur)setMode(mode==='place'?null:'place')},clearPos:()=>{if(cur){setPosition(null,null);$('f-unc').value=''}},
  nextDet:()=>stepDet(1),prevDet:()=>stepDet(-1),nextImage:()=>{if(img&&confirmLeave())openImage(img.provider,img.image_id,img.view,1,true)},prevImage:()=>{if(img&&confirmLeave())openImage(img.provider,img.image_id,img.view,-1,true)},
  nextView:()=>stepView(1),prevView:()=>stepView(-1),zoomFit:()=>{if(cur&&!boxZoom){zoomToBox(true);boxZoom=true}else{fitImage(true);boxZoom=false}},
  centerMap:()=>{const c=cameraFor();if(c)map.setView(c,Math.max(map.getZoom(),18))},streetView:()=>{const a=$('streetview');if(a.getAttribute('aria-disabled')!=='true')window.open(a.href,'_blank','noopener')},
  ocr,queueList:()=>toggleQueueList(),help:()=>openSettings('keys'),settings:()=>openSettings('general')};
for(let i=0;i<10;i++)run['class'+i]=()=>{if(cur&&LABELS[i])setLabel(LABELS[i])};
function pickDecision(d){if(!cur)return;setDecision(d);if(d==='duplicate')setMode('pick-duplicate');else if(mode==='pick-duplicate')setMode(null);if(S.quick&&(d==='reject'||d==='uncertain'))save()}
function stepDet(dir){if(!img?.detections.length)return;const i=img.detections.findIndex(x=>x.id===cur?.id),n=img.detections[(i+dir+img.detections.length)%img.detections.length];if(n&&n.id!==cur?.id&&confirmLeave())loadObservation(n.id,false)}
let capturing=null;
document.addEventListener('keydown',e=>{
  if(capturing)return captureKey(e);
  if($('settings').open)return;
  const k=combo(e),typing=/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
  if(e.key==='Escape'){if(mode){setMode(null);e.preventDefault();return}if(!$('queue-panel').hidden){toggleQueueList(false);return}if(typing)e.target.blur();return}
  if(typing&&!(e.ctrlKey||e.metaKey))return;
  const action=keymap.get(k);if(!action)return;e.preventDefault();run[action]?.()});

// ------------------------------------------------------------------ splitter
const splitter=$('splitter'),mapPane=$('map-pane');
function setSplit(pct,save=true){pct=Math.max(20,Math.min(80,pct));mapPane.style.flexBasis=pct+'%';splitter.setAttribute('aria-valuenow',Math.round(pct));if(save){S.split=pct;persist()}requestAnimationFrame(()=>map.invalidateSize())}
splitter.addEventListener('pointerdown',e=>{splitter.setPointerCapture(e.pointerId);splitter.classList.add('dragging');document.body.classList.add('resizing')});
splitter.addEventListener('pointermove',e=>{if(!splitter.hasPointerCapture(e.pointerId))return;const r=$('workspace').getBoundingClientRect();setSplit(100*(e.clientX-r.left)/r.width,false)});
splitter.addEventListener('pointerup',()=>{splitter.classList.remove('dragging');document.body.classList.remove('resizing');S.split=Number(splitter.getAttribute('aria-valuenow'));persist();map.invalidateSize()});
splitter.addEventListener('dblclick',()=>setSplit(DEFAULTS.split));
splitter.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();e.stopPropagation();setSplit(Number(splitter.getAttribute('aria-valuenow'))+(e.key==='ArrowLeft'?-2:2))}});
window.addEventListener('resize',()=>map.invalidateSize());

// ------------------------------------------------------------------ settings
function openSettings(tab){showTab(tab);syncSettingsForm();$('settings').showModal()}
function showTab(tab){document.querySelectorAll('.tabs [data-tab]').forEach(b=>b.setAttribute('aria-selected',b.dataset.tab===tab));document.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==tab)}
document.querySelectorAll('.tabs [data-tab]').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
function applyTheme(){if(S.theme==='system')delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=S.theme}
function syncSettingsForm(){$('s-theme').value=S.theme;$('s-unc').value=S.defaultUnc;$('s-quick').checked=S.quick;$('s-zoombox').checked=S.zoomToBox;$('s-follow').checked=S.follow;
  $('s-basemap').replaceChildren(...Object.keys(basemaps).map(n=>new Option(n,n,false,n===S.basemap)));$('s-size').value=S.markerSize;
  for(const [id,k] of [['s-cameras','cameras'],['s-est-multi','estMulti'],['s-est-single','estSingle'],['s-placed','placed'],['s-rays','rays']])$(id).checked=S.layers[k];
  $('s-colors').innerHTML=LABELS.map(l=>`<label><input type="color" data-class="${esc(l)}" value="${color(l)}">${esc(l)}</label>`).join('');
  $('s-colors').querySelectorAll('input').forEach(i=>i.oninput=()=>{S.colors[i.dataset.class]=i.value;persist();restyle()});renderKeyTable()}
function restyle(){drawEstimates();drawPlaced();drawCameras();drawSelection();renderDetections()}
$('s-theme').onchange=()=>{S.theme=$('s-theme').value;persist();applyTheme()};
$('s-unc').onchange=()=>{const v=Number($('s-unc').value);if(v>0){S.defaultUnc=v;persist()}};
for(const [id,k] of [['s-quick','quick'],['s-zoombox','zoomToBox'],['s-follow','follow']])$(id).onchange=()=>{S[k]=$(id).checked;persist()};
$('s-basemap').onchange=()=>{S.basemap=$('s-basemap').value;persist();for(const [n,l] of Object.entries(basemaps))n===S.basemap?l.addTo(map):l.remove()};
$('s-size').oninput=()=>{S.markerSize=Number($('s-size').value);persist();restyle()};
for(const [id,k] of [['s-cameras','cameras'],['s-est-multi','estMulti'],['s-est-single','estSingle'],['s-placed','placed'],['s-rays','rays']])$(id).onchange=()=>{S.layers[k]=$(id).checked;persist();applyLayerVisibility();drawSelection()};
$('s-colors-reset').onclick=()=>{S.colors={};persist();syncSettingsForm();restyle()};
$('s-keys-reset').onclick=()=>{S.hotkeys={};persist();rebuildKeymap();renderKeyTable()};
function renderKeyTable(){const counts={};for(const [id] of allActions()){const k=keyFor(id);if(k)counts[k]=(counts[k]||0)+1}
  $('s-keys').innerHTML=allActions().map(([id,label])=>{const k=keyFor(id);return `<tr class="${k&&counts[k]>1?'conflict':''}"><td>${esc(label)}</td><td><button type="button" data-action="${id}" title="${k&&counts[k]>1?'Conflicts with another action':'Click, then press a key'}">${esc(pretty(k)||'unassigned')}</button></td></tr>`}).join('');
  $('s-keys').querySelectorAll('button').forEach(b=>b.onclick=()=>{capturing=b.dataset.action;b.classList.add('capturing');b.textContent='Press keys…'})}
function captureKey(e){if(['Shift','Control','Alt','Meta'].includes(e.key))return;e.preventDefault();e.stopPropagation();const id=capturing;capturing=null;
  if(e.key==='Backspace')S.hotkeys[id]='';else if(e.key!=='Escape')S.hotkeys[id]=combo(e);persist();rebuildKeymap();renderKeyTable()}
$('settings').addEventListener('cancel',e=>{if(capturing){e.preventDefault()}});
$('open-settings').onclick=()=>openSettings('general');$('open-help').onclick=()=>openSettings('keys');

// ------------------------------------------------------------------ wiring
document.querySelectorAll('.decision button').forEach(b=>b.onclick=()=>pickDecision(b.dataset.decision));
$('inspector').addEventListener('submit',e=>{e.preventDefault();save()});
for(const id of ['f-text','f-notes','f-unc','f-vis','f-occ','f-role','f-asset'])$(id).addEventListener('input',setDirty);
$('f-label').onchange=()=>setLabel($('f-label').value);
$('use-estimate').onclick=useEstimate;$('place').onclick=run.place;$('clear-pos').onclick=run.clearPos;$('ocr').onclick=ocr;$('skip').onclick=skip;$('undo').onclick=undo;
$('img-prev').onclick=run.prevImage;$('img-next').onclick=run.nextImage;$('zoom-fit').onclick=run.zoomFit;
$('streetview').onclick=e=>{if($('streetview').getAttribute('aria-disabled')==='true')e.preventDefault()};
$('q-prev').onclick=run.prevItem;$('q-next').onclick=()=>{if(confirmLeave()){dirty=false;stepQueue(1)}};$('q-list-toggle').onclick=()=>toggleQueueList();
$('q-page-prev').onclick=()=>{if(confirmLeave()){Q.offset=Math.max(0,Q.offset-Q.limit);loadQueue(0)}};$('q-page-next').onclick=()=>{if(confirmLeave()){Q.offset+=Q.limit;loadQueue(0)}};
for(const id of ['q-class','q-status','q-sort'])$(id).onchange=()=>{if(!confirmLeave())return;dirty=false;Q.offset=0;loadQueue(0)};
$('q-search').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();Q.offset=0;loadQueue(0)}});
$('reviewer').value=localStorage.getItem('asset-reviewer')||'';$('reviewer').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();$('reviewer').blur();try{localStorage.setItem('asset-reviewer',$('reviewer').value.trim())}catch(x){}if(cur&&decision)save()}});$('reviewer').addEventListener('change',()=>{try{localStorage.setItem('asset-reviewer',$('reviewer').value.trim())}catch(e){}});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});

(async function init(){applyTheme();setSplit(S.split,false);applyLayerVisibility();
  try{session=await api('/api/session')}catch(e){$('stage-message').textContent='Cannot reach the review server. Start it with: python review_server.py, then open http://localhost:8001';$('stats').textContent='Offline';return}
  LABELS=session.labels;for(const l of LABELS){$('f-label').append(new Option(l,l));$('q-class').append(new Option(l,l))}$('f-label').append(new Option('unknown','unknown'));
  rebuildKeymap();refreshStats();
  CameraPositions.install(map,()=>{drawCameras();drawSelection()});await CameraPositions.ready;
  const mapReady=loadMapData();
  const hash=new URLSearchParams(location.hash.slice(1)),deep=hash.get('obs');if(hash.get('settings'))openSettings(hash.get('settings'));if(deep){await loadObservation(deep,false);loadQueue(0,false)}else await loadQueue(0);
  // Town-wide view only when nothing is selected; otherwise the map follows the camera.
  await mapReady;if(!img&&cameraData.length)map.fitBounds(L.latLngBounds(cameraData.map(c=>[c[3],c[2]])),{padding:[20,20],animate:false})})();
