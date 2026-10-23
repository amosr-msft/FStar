#!/usr/bin/env python3

import argparse
import glob
import hashlib
import json
import re
import statistics
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--evidence-root", type=Path, required=True)
parser.add_argument("--worktree-prefix", type=Path, required=True)
parser.add_argument("--z3", type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parent
root = args.evidence_root.resolve()
worktree_prefix = args.worktree_prefix.resolve()
z3 = args.z3.resolve()
def sha256(path):
 h=hashlib.sha256()
 with Path(path).open("rb") as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b""): h.update(chunk)
 return h.hexdigest()
variants=('original-a','original-b','fusion','combined'); modules=('BenchBvLive500','BenchUIntLive500')
e2e=[json.loads(x) for x in open(root/'matched-e2e-isolated/measurements.jsonl')]
prof=[json.loads(x) for x in open(root/'matched-profiles/measurements.jsonl')]
detail=json.load(open(root/'matched-detailed-phases/measurements.json'))
ordinary=json.load(open(root/'matched-ordinary/measurements.json'))
for row in detail:
 if row["mode"] == "write":
  if "store_values_to_cache_wall_ms" not in row:
   raise RuntimeError("write row missing storage timing")
 else:
  if "store_values_to_cache_wall_ms" in row:
   raise RuntimeError("no-write row unexpectedly stored a checked file")
  row["store_values_to_cache_wall_ms"] = 0
expected = [
 ("end-to-end", e2e, {(v,m,mode,i) for v in variants for m in modules for mode in ("write","no-write") for i in range(1,6)}, lambda x:(x["variant"],x["module"],x["mode"],x["repeat"])),
 ("profiles", prof, {(v,m,i) for v in variants for m in modules for i in range(1,4)}, lambda x:(x["variant"],x["module"],x["repeat"])),
 ("detailed", detail, {(v,m,mode,i) for v in variants for m in modules for mode in ("write","no-write") for i in range(1,3)}, lambda x:(x["variant"],x["module"],x["mode"],x["repeat"])),
 ("ordinary", ordinary, {(v,m,mode,i) for v in variants for m in ("Positivity","TestWellFoundedRecursion") for mode in ("write","no-write") for i in range(1,6)}, lambda x:(x["variant"],x["module"],x["mode"],x["repeat"])),
]
for name, rows, keys, key in expected:
 actual={key(row) for row in rows}
 if actual != keys or len(rows) != len(keys):
  raise RuntimeError(f"{name}: expected exact {len(keys)}-cell matrix")
def med(xs): return statistics.median(xs)
def summarize(rows, module, variant, mode=None, keys=('wall_seconds',)):
 z=[x for x in rows if x['module']==module and x['variant']==variant and (mode is None or x.get('mode')==mode)]
 out={}
 for k in keys:
  if any(k not in x for x in z): raise RuntimeError(f"{module}/{variant}: missing {k}")
  xs=[x[k] for x in z]; out[k]={'observations':xs,'median':med(xs),'min':min(xs),'max':max(xs)}
 return out
commits={'original-a':'b3f9782a6c3c02f2a91705aa00ee936361b5df27','original-b':'b3f9782a6c3c02f2a91705aa00ee936361b5df27','fusion':'206126a6dd6649765d6980e95609c5fda71888e9','combined':'befb3db82018af3dadf556fafdd95295b2751081'}
variant_info={}
for variant in variants:
 worktree=Path(str(worktree_prefix)+"-"+variant)
 actual_commit=subprocess.check_output(["git","-C",str(worktree),"rev-parse","HEAD"],text=True).strip()
 if actual_commit != commits[variant]: raise RuntimeError(f"{variant}: wrong commit")
 binary=worktree/'stage3/out/bin/fstar.exe'
 extracted=worktree/'stage2/fstarc.ml/FStarC_SMTEncoding_Sharing.ml'
 version=subprocess.check_output([str(binary),"--version"],text=True)
 ocaml=re.search(r"compiler=OCaml ([^\n]+)",version).group(1)
 embedded_commit=re.search(r"commit=([^\n]+)",version).group(1)
 variant_info[variant]={'source_commit':commits[variant],'worktree_head':actual_commit,'binary_embedded_commit':embedded_commit,'binary_sha256':sha256(binary),'binary_bytes':binary.stat().st_size,'extracted_sharing_sha256':sha256(extracted),'extracted_sharing_bytes':extracted.stat().st_size,'ocaml':ocaml}
 changed=subprocess.check_output(["git","-C",str(worktree),"diff","--name-only","b3f9782a6c",commits[variant]],text=True).splitlines()
 if any(path != "src/smtencoding/FStarC.SMTEncoding.Sharing.fst" for path in changed):
  raise RuntimeError(f"{variant}: non-sharing source differs")
z3_version=subprocess.check_output([str(z3),"--version"],text=True).strip()
if "5.3.0" not in z3_version: raise RuntimeError(f"unexpected solver: {z3_version}")
out={'date':'2026-10-23','variants':variant_info,
'build':{'matched_build_procedure':'Recorded in README and build-log hashes; same copied bootstrap stages and make target.','fusion_binary_source_state':'Built from the uncommitted fusion-only diff while HEAD was b3f9782a6c; binary reports b3f9782a6c-dirty. The exact extracted sharing module hash is recorded and matches the source later committed unchanged as 206126a6dd.','non_sharing_git_diff_verified_empty':True,'original_extracted_modules_identical':variant_info['original-a']['extracted_sharing_sha256']==variant_info['original-b']['extracted_sharing_sha256'],'original_binaries_identical':variant_info['original-a']['binary_sha256']==variant_info['original-b']['binary_sha256'],'z3_version':z3_version,'z3_sha256':sha256(z3),'measured_rows_z3_path_recorded':False,'z3_limitation':'Audited campaign invocation supplied this z3-bin-dir and successful runs required version 5.3.0, but legacy raw rows record --z3version rather than the resolved PATH executable. Current runners pass --smt explicitly.','note':'Original A/B are identical-source rebuild controls. Git diffs verify fusion and combined differ only in Sharing.fst. Different original executable hashes/sizes establish residual build-layout nondeterminism.'},
'end_to_end':{'repetitions_per_cell':5,'order_seed':4765,'observed_overlap_attempts_excluded':(root/'matched-e2e-isolated/campaign.log').read_text().count('RETRY external overlap'),'overlap_detector_limitations':'One-second polling of ps command-line strings can miss short overlaps, can produce false positives from command text, and does not detect another invocation containing the same compiler path.','modules':{}},
'broad_profiles':{'repetitions_per_variant_module':3,'modules':{}},
'detailed_phases':{'repetitions_per_variant_module_mode':2,'modules':{}},
'ordinary_controls':{},
'isolated_input_audit':{'production_order':['encode_signature fresh graph','intern_decls','summarize_elts','intern_index','optional solver registration','optional checked serialization'],'checked_file_contains':'post-intern declarations and index','isolated_harness_input':'serialized post-intern graph, not production pre-intern graph','full_gc_before_each_pass':True,'warmup':'original twice; fusion and combined once','retains_output_until_reachable_words':True,'bv_recovery_bytes_unchanged':True,'uint_recovery_bytes_unchanged':True,'second_recovery_is_digest_fixed_point':True},
'evidence_sha256':{}}
out["instrumented_binaries"] = {
 name: {
  variant: sha256(root / directory / f"fstar-{variant}.exe")
  for variant in variants
 }
 for name, directory in (
  ("broad_profiles", "matched-instrumented"),
  ("detailed_phases", "matched-instrumented-phases"),
 )
}
for m in modules:
 out['end_to_end']['modules'][m]={}
 for v in variants:
  out['end_to_end']['modules'][m][v]={mode:summarize(e2e,m,v,mode,('wall_seconds','user_seconds','fstar_mempeak_bytes','max_rss_kb','checked_bytes')) for mode in ('write','no-write')}
 out['broad_profiles']['modules'][m]={}
 for v in variants:
  summary=summarize(prof,m,v,None,('total_profile_ms','z3_aggregate_ms','intern_decls_ms','intern_index_ms','decls_allocated_words','index_allocated_words','allocated_words','promoted_words','major_words','minor_collections','major_collections','top_heap_words'))
  logs=glob.glob(str(root/f'matched-profiles/*-{m}-{v}.log'))
  counters={}
  for name in ('FStarC.TypeChecker.Tc.process_one_decl','FStarC.TypeChecker.Tc.tc_sig_let-tc-phase2','FStarC.TypeChecker.Rel.simplify_vc','FStarC.TypeChecker.Tc.encode_sig','FStarC.SMTEncoding.EncodeTerm.normalize_refinement','FStarC.SMTEncoding.Encode.norm_before_encoding'):
   xs=[]
   for p in logs:
    text=open(p).read(); q=re.search(re.escape(m)+r', profiled '+re.escape(name)+r':\s+(\d+) ms',text); xs.append(int(q.group(1)) if q else 0)
   counters[name]={'observations':xs,'median':med(xs)}
  loads=[sum(map(int,re.findall(r'profiled FStarC\.CheckedFiles:\s+(\d+) ms',open(p).read()))) for p in logs]
  counters['FStarC.CheckedFiles.sum']={'observations':loads,'median':med(loads)}
  summary['phase_counters']=counters; out['broad_profiles']['modules'][m][v]=summary
 out['detailed_phases']['modules'][m]={}
 for v in variants:
  out['detailed_phases']['modules'][m][v]={mode:summarize(detail,m,v,mode,('wall_seconds','encode_signature_wall_ms','decls_wall_ms','decls_allocated_words','summarize_elts_wall_ms','index_wall_ms','index_allocated_words','give_index_to_z3_wall_ms','store_values_to_cache_wall_ms','allocated_words','promoted_words','major_words','minor_collections','major_collections','top_heap_words')) for mode in ('write','no-write')}
for m in ('Positivity','TestWellFoundedRecursion'):
 out['ordinary_controls'][m]={v:{mode:summarize(ordinary,m,v,mode,('wall_seconds','fstar_mempeak_bytes','checked_bytes')) for mode in ('write','no-write')} for v in variants}
for name in ("bv","uint"):
 first=(root/f"matched-input-audit/{name}.log").read_text()
 second=(root/f"matched-input-audit/{name}2.log").read_text()
 in_bytes,out_bytes=re.search(r"input_bytes=(\d+) output_bytes=(\d+)",first).groups()
 if in_bytes != out_bytes: raise RuntimeError(f"{name}: recovery changed size")
 in_digest,out_digest=re.search(r"input_digest=(\w+) output_digest=(\w+)",second).groups()
 if in_digest != out_digest: raise RuntimeError(f"{name}: second recovery not fixed point")
def log_manifest(directory, expected_count):
 entries=[]
 paths=sorted(path for path in Path(directory).glob("*.log") if path.name != "campaign.log")
 if len(paths) != expected_count: raise RuntimeError(f"{directory}: expected {expected_count} logs")
 for path in paths:
  entries.append(f"{sha256(path)}  {path.name}\\n")
 return hashlib.sha256("".join(entries).encode()).hexdigest()
files={'end_to_end_jsonl':root/'matched-e2e-isolated/measurements.jsonl','end_to_end_log':root/'matched-e2e-isolated/campaign.log','broad_profiles_jsonl':root/'matched-profiles/measurements.jsonl','detailed_phases_json':root/'matched-detailed-phases/measurements.json','ordinary_json':root/'matched-ordinary/measurements.json','input_audit_bv':root/'matched-input-audit/bv.log','input_audit_bv_fixed_point':root/'matched-input-audit/bv2.log','input_audit_uint':root/'matched-input-audit/uint.log','input_audit_uint_fixed_point':root/'matched-input-audit/uint2.log','original_a_build_log':root/'matched-original-a-build.log','original_b_build_log':root/'matched-original-b-build.log','fusion_build_log':root/'fstar-fusion-only-build.log','combined_build_log':root/'matched-combined-build.log','run_matched_variants':repo/'run_matched_variants.py','run_matched_profiles':repo/'run_matched_profiles.py','run_matched_detailed_phases':repo/'run_matched_detailed_phases.py','run_matched_ordinary':repo/'run_matched_ordinary.py','instrument_extracted_analysis':repo/'instrument_extracted_analysis.py'}
out['evidence_sha256']={name:sha256(path) for name,path in files.items()}
out['evidence_sha256']['broad_profile_logs_manifest'] = log_manifest(root/'matched-profiles',24)
out['evidence_sha256']['detailed_phase_logs_manifest'] = log_manifest(root/'matched-detailed-phases',32)
(repo/'MATCHED_END_TO_END_ANALYSIS.json').write_text(json.dumps(out,indent=2)+'\n')
