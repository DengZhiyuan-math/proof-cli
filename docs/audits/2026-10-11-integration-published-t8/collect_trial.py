"""Read trial state through the published core APIs; do not edit project state."""
import hashlib
import json
from pathlib import Path
import sys

out=Path(__file__).resolve().parent
manifest=json.loads((out/'manifest.json').read_text())
sys.path.insert(0,manifest['repositories']['core']['sourcePath']+'/src')
from proof_cli.storage import ensure_project, read_scope
from proof_cli.definitions import all_definitions
from proof_cli.fog import list_fog
from proof_cli.proof_map import list_nodes, questions, work_log, get_acceptance_state, get_reference_review_state, get_integrity_state, is_provisional, conditional_on

preflight=json.loads((out/'real-trial-preflight.json').read_text())
store=ensure_project(Path(preflight['root']))
with read_scope():
    nodes=list_nodes(store)
    data={'nodes':[n.model_dump(mode='json') for n in nodes], 'definitions':[d.model_dump(mode='json') for d in all_definitions(store)], 'fog':[f.model_dump(mode='json') for f in list_fog(store,include_all=True)], 'nodeState':{n.id:{'questions':questions(store,n.id),'workLog':work_log(store,n.id),'integrity':str(get_integrity_state(store,n.id)),'provisional':is_provisional(store,n.id),'conditionalOn':sorted(conditional_on(store,n.id)),'acceptance':str(get_acceptance_state(store,n.id)),'referenceReview':str(get_reference_review_state(store,n.id)) if n.kind.value=='imported_result' else None} for n in nodes}}
data['inputSHA256']=hashlib.sha256(Path(preflight['input']['copy']).read_bytes()).hexdigest()
assert data['inputSHA256']==preflight['input']['sha256']
(out/'real-project-details.json').write_text(json.dumps(data,indent=2,default=str)+'\n')
print('Trial snapshot:',len(data['nodes']),'nodes,',len(data['definitions']),'Definitions,',len(data['fog']),'fog entries')
