"""Read-only T8 progress and terminal snapshot recorder."""
import datetime
import json
from pathlib import Path
import time
import urllib.request

out=Path(__file__).resolve().parent
url=json.loads((out/'real-server.json').read_text())['url']
last=None
while True:
    def get(route):
        with urllib.request.urlopen(url+route,timeout=10) as response:return json.load(response)['data']
    view=get('/api/pursue')
    marker=(view['status'],view.get('current'),view.get('budget',{}).get('spent'),view.get('reason'))
    if marker!=last:
        at=datetime.datetime.now(datetime.timezone.utc).isoformat()
        with (out/'real-progress.jsonl').open('a') as log:log.write(json.dumps({'at':at,'view':view})+'\n')
        print(at,marker,flush=True)
        last=marker
    (out/'real-current.json').write_text(json.dumps(view,indent=2)+'\n')
    if view['status'] not in ('starting','reading','pursuing','stopping') and not view.get('stopping'):
        (out/'real-ended.json').write_text(json.dumps({'observedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'view':view},indent=2)+'\n')
        for route,name in [('/api/map','real-map.json'),('/api/review-queue','real-queue.json'),('/api/state','real-state.json')]:
            (out/name).write_text(json.dumps(get(route),indent=2)+'\n')
        print('Terminal trial snapshots saved',flush=True)
        break
    time.sleep(10)
