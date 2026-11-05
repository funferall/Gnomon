import requests, time, json
places={'Boston':(42.3601,-71.0589),'Worcester':(42.2626,-71.8023),'Springfield':(42.1015,-72.5898),'Pittsfield':(42.4501,-73.2454),'Lowell':(42.6334,-71.3162),'Barnstable':(41.7003,-70.3002),'Cambridge':(42.3736,-71.1097),'Somerville':(42.3876,-71.0995),'New Bedford':(41.6362,-70.9342),'Fall River':(41.7015,-71.1550),'Brockton':(42.0834,-71.0184),'Quincy':(42.2529,-71.0023),'Plymouth':(41.9584,-70.6673),'Amherst':(42.3732,-72.5199),'Northampton':(42.3251,-72.6412),'Greenfield':(42.5876,-72.5995),'North Adams':(42.7009,-73.1087),'Framingham':(42.2793,-71.4162),'Lawrence':(42.7070,-71.1631),'Salem':(42.5195,-70.8967),'Hyannis':(41.6525,-70.2828),'Provincetown':(42.0584,-70.1786),'Martha Vineyard':(41.4543,-70.6036),'Nantucket':(41.2835,-70.0995)}
results=[];images={}
for name,(lat,lon) in places.items():
 try:
  r=requests.get('https://api.kartaview.org/2.0/photo/',params={'lat':lat,'lng':lon,'zoomLevel':15,'join':'sequence','itemsPerPage':50,'orderBy':'id','orderDirection':'desc'},timeout=25);r.raise_for_status();j=r.json();data=j['result']['data'];more=j['result'].get('hasMoreData');results.append({'place':name,'lat':lat,'lon':lon,'returned':len(data),'has_more':more,'status':j['status']});images.update({str(d['id']):d for d in data});print(name,len(data),'more',more,flush=True)
 except Exception as e:results.append({'place':name,'lat':lat,'lon':lon,'error':str(e)});print(name,'ERROR',str(e),flush=True)
 time.sleep(.3)
json.dump({'description':'First page per selected point, zoomLevel=15. Not statewide coverage or a representative sample. dateAdded is upload date, not capture date.','samples':results,'images':list(images.values())},open('data/kartaview_samples.json','w',encoding='utf-8'),indent=2)
