/* Official MassGIS cached services use Web Mercator XYZ-compatible ArcGIS tiles. */
window.addMassGISBasemaps=function(map,selected='2025'){
 const root='https://tiles.arcgis.com/tiles/hGdibHYSPO59RG1h/arcgis/rest/services/';
 const layers={
  'MassGIS imagery · 2025':L.tileLayer(root+'Massachusetts_Aerial_Imagery_2025/MapServer/tile/{z}/{y}/{x}',{maxZoom:23,attribution:'Imagery: MassGIS, spring 2025'}),
  'MassGIS imagery · 2023':L.tileLayer(root+'orthos2023/MapServer/tile/{z}/{y}/{x}',{maxZoom:23,attribution:'Imagery: MassGIS, spring 2023'}),
  'MassGIS imagery · 2021':L.tileLayer(root+'orthos2021/MapServer/tile/{z}/{y}/{x}',{maxZoom:23,attribution:'Imagery: MassGIS, spring 2021'}),
  'MassGIS basemap':L.tileLayer(root+'MassGISBasemap/MapServer/tile/{z}/{y}/{x}',{maxZoom:23,attribution:'MassGIS basemap'}),
  'OpenStreetMap':L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:23,maxNativeZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'})
 };
 const chosen=Object.keys(layers).find(k=>k.includes(selected))||Object.keys(layers)[0];layers[chosen].addTo(map);L.control.layers(layers,null,{position:'topright',collapsed:false}).addTo(map);return layers;
};
