"""T8 controlled provider on the exact published sources; no model calls."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import runpy

out = Path(__file__).resolve().parent
manifest = json.loads((out/'manifest.json').read_text())
r = manifest['repositories']
sources = [r['core']['sourcePath']+'/src', r['core']['sourcePath']+'/packages/latex-agent/src', r['agents']['sourcePath']+'/src', r['web']['sourcePath']+'/src']
os.environ['PYTHONPATH'] = os.pathsep.join(sources)
for path in [*sources, r['web']['sourcePath']+'/tests']:
    sys.path.insert(0, path)
from latex_agent import agent
from latex_agent.backends import Backend
from proof_cli.proof_map import create_node, list_nodes, record_progress, split_node, record_evidence_check
from proof_cli.definitions import add_definition
from proof_cli.storage import ensure_project
from proof_web.server import ReviewServer
from _proofs import submit_proof

parser=argparse.ArgumentParser()
parser.add_argument('scenario',choices=['lifecycle','no-theorem','parked','queue','release-retry','release-interrupted','real'])
parser.add_argument('--root',type=Path)
parser.add_argument('--port',type=int,default=None)
args=parser.parse_args()
root=args.root or out/'projects'/args.scenario
if args.scenario.startswith('release-'):
    sys.argv=['browser_server.py',args.scenario,str(root)]
    runpy.run_path(str(out.parent/'2026-10-10-web10-07bb06e-publication-browser/browser_server.py'),run_name='__main__')
    raise SystemExit
store=ensure_project(root,project_id='t8-'+args.scenario)
if args.scenario!='real':
    (root/'library').mkdir(exist_ok=True)
    (root/'library/main.tex').write_text('\\begin{theorem}T holds.\\end{theorem}\n')
    (root/'proof.toml').write_text('[studio]\nlibrary=["library"]\nparallel=1\nagent_name="t8-controlled"\nbudget_turns=' + ('1' if args.scenario=='parked' else '4') + '\nbudget_minutes=5\n')
if args.scenario=='parked' and not list_nodes(store):
    create_node(store,node_id='T',kind='theorem',statement='T holds',created_by='reader-fixture')
    split_node(store,'T',[{'id':'A','statement':'A holds'}],created_by='decomposer-fixture')
if args.scenario=='queue' and not list_nodes(store):
    add_definition(store,'D',term='Positive parameter',text='$n \\ge 1$.',created_by='reader-fixture')
    create_node(store,node_id='R',kind='imported_result',statement='A cited result',source_locator='fixture theorem 1',source_version='v1',created_by='reader-fixture')
    create_node(store,node_id='C',kind='claim',statement='C holds for n.',definitions=['D'],created_by='decomposer-fixture')
    create_node(store,node_id='L',kind='lemma',statement='L follows from C and R.',dependencies=['C','R'],created_by='reader-fixture')
    create_node(store,node_id='T',kind='theorem',statement='T follows from L.',dependencies=['L'])
    proof=submit_proof(store,'C',claimant_id='prover-fixture',scoping_rationale='controlled snapshot',content='A controlled fixture proof.')
    record_evidence_check(store,proof.id,'passed',run_by='prover-fixture/verifier',notes='controlled fixture, not mathematics')
    record_progress(store,'C',role='prover',by='prover-fixture',question='took n >= 1; the alternative is n >= 2')
    (root/'scratch/reader').mkdir(parents=True,exist_ok=True)
    (root/'scratch/reader/departures.md').write_text('Controlled fixture: stated the parameter explicitly.\n')
class Controlled(Backend):
    def run(self,job):
        role=getattr(job.context,'role','reader'); node=getattr(job.context,'node_id',None)
        with (root/'controlled-turns.jsonl').open('a') as log:
            log.write(json.dumps({'role':role,'node':node,'at':time.time()})+'\n')
        job.emit({'t':'text','text':'T8 controlled provider; no model call.'})
        if args.scenario=='lifecycle':
            while not (root/'allow-finish').exists() and not job.cancel.wait(.1): pass
            if not job.cancel.is_set() and not list_nodes(store):
                create_node(store,node_id='T',kind='theorem',statement='T holds',created_by='reader-fixture')
        elif args.scenario=='parked':
            record_progress(store,node,role=role,by=job.context.name,step=1,status='done',note='controlled Prover turn complete; next role exceeds the one-turn budget')
        return {'exit':0}
if args.scenario!='real':
    backend=Controlled('t8-controlled')
    agent.load_backends=lambda:({backend.id:backend},backend.id,None)
if args.scenario=='real':
    # Observe provider identity and completion without changing the job events.
    from latex_agent.backends import Job
    emit = Job.emit
    def observed_emit(job, event):
        if event.get('t') in ('init', 'done'):
            item = {'at':time.time(), 'job':job.id, 'role':getattr(job.context,'role','reader'), 'node':getattr(job.context,'node_id',None), 'event':{k:v for k,v in event.items() if k in ('t','model','exit','is_error','subtype','stderr','usage','cost')}}
            with (out/'real-provider-events.jsonl').open('a') as log:
                log.write(json.dumps(item)+'\n')
        return emit(job, event)
    Job.emit = observed_emit
server=ReviewServer(store,port=args.port)
info={'pid':os.getpid(),'url':server.url,'scenario':args.scenario,'root':str(root)}
(out/(args.scenario+'-server.json')).write_text(json.dumps(info,indent=2)+'\n')
print(json.dumps(info),flush=True)
try: server.serve_forever()
except KeyboardInterrupt: pass
finally: server.server_close()
