#!/usr/bin/env python3

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def parse_events(path):
    data = json.loads(path.read_text())
    parsed = {}
    for line in data["events"]:
        fields = line.split(",")
        kind = fields[0].removeprefix("CONTEXT_")
        number = int(fields[1])
        values = [float(value) for value in fields[2:]]
        parsed.setdefault(kind, {})[number] = values
    return data["command"], parsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_root.resolve()
    worktree = args.worktree.resolve()
    files = {
        "scaling": evidence / "bv-simple-scaling/measurements.jsonl",
        "scaling_provenance": evidence / "bv-simple-scaling/provenance.json",
        "probes": evidence / "bv-simple-probes/measurements.jsonl",
        "probes_provenance": evidence / "bv-simple-probes/provenance.json",
        "trace_1024": evidence / "bv-context-trace-v2/events.json",
        "trace_1024_provenance":
            evidence / "bv-context-trace-v2/provenance.json",
        "trace_no_ambients_1024":
            evidence / "bv-context-trace-no-ambients/events.json",
        "trace_no_ambients_1024_provenance":
            evidence / "bv-context-trace-no-ambients/provenance.json",
        "flush_trace": evidence / "bv-context-flush-trace/events.json",
        "flush_trace_provenance":
            evidence / "bv-context-flush-trace/provenance.json",
        "flush_trace_no_ambients":
            evidence / "bv-context-flush-trace-no-ambients/events.json",
        "flush_trace_no_ambients_provenance":
            evidence / "bv-context-flush-trace-no-ambients/provenance.json",
        "debug_trace": evidence / "bv-context-trace-debug/trace.log",
        "debug_trace_provenance":
            evidence / "bv-context-trace-debug/provenance.json",
        "full_no_ambients":
            evidence / "bv-full-no-ambients/measurements.jsonl",
        "full_no_ambients_provenance":
            evidence / "bv-full-no-ambients/provenance.json",
    }
    provenance = {
        name: json.loads(path.read_text())
        for name, path in files.items()
        if name.endswith("_provenance")
    }
    historical_commit = "0e13baff38309523a2074ef8fbc3745b4bc793ad"
    z3_hashes = {
        item["z3_sha256"] for item in provenance.values()
    }
    require(len(z3_hashes) == 1, "diagnostics used different Z3 binaries")
    rebuilt_hash = provenance["scaling_provenance"]["fstar_sha256"]
    require(
        provenance["probes_provenance"]["fstar_sha256"] == rebuilt_hash
        and provenance["full_no_ambients_provenance"]["fstar_sha256"]
        == rebuilt_hash,
        "production diagnostics used different rebuilt compilers",
    )
    require(
        provenance["scaling_provenance"]["generator_sha256"]
        == digest(Path(__file__).resolve().parent / "generate_simple.py")
        == provenance["probes_provenance"]["generator_sha256"],
        "simple generator provenance differs",
    )
    require(
        provenance["scaling_provenance"]["timeout_seconds"] == 1200
        and len(provenance["scaling_provenance"]["plan"]) == 70,
        "scaling plan or timeout differs",
    )
    for name in (
        "trace_1024_provenance",
        "trace_no_ambients_1024_provenance",
        "flush_trace_provenance",
        "flush_trace_no_ambients_provenance",
        "debug_trace_provenance",
    ):
        require(
            provenance[name]["worktree_commit"] == historical_commit,
            f"{name} used a different worktree",
        )
    for left, right in (
        ("trace_1024_provenance", "trace_no_ambients_1024_provenance"),
        ("flush_trace_provenance", "flush_trace_no_ambients_provenance"),
    ):
        for field in (
            "fstar_sha256", "source_sha256", "instrumenter_sha256",
            "prims_checked_sha256",
        ):
            require(
                provenance[left][field] == provenance[right][field],
                f"{left} and {right} differ in {field}",
            )
    require(
        provenance["trace_no_ambients_1024_provenance"]["no_ambients"]
        is True
        and provenance["flush_trace_no_ambients_provenance"]["no_ambients"]
        is True
        and provenance["flush_trace_provenance"]["no_ambients"] is False,
        "trace modes differ",
    )

    scaling = read_rows(files["scaling"])
    monolithic = [row for row in scaling if row["groups"] == 1]
    split = [row for row in scaling if row["groups"] == 64]
    require(len(monolithic) == 6, "expected six monolithic rows")
    require(len(split) == 64, "expected 64 split rows")
    require(
        sorted(row["group"] for row in split) == list(range(64)),
        "split groups are incomplete",
    )
    require(
        sum(row["declarations"] for row in split) == 5808,
        "split declaration count differs",
    )
    row_keys = {
        (row["count"], row["groups"], row["group"]) for row in scaling
    }
    plan_keys = {
        (row["count"], row["groups"], row["group"])
        for row in provenance["scaling_provenance"]["plan"]
    }
    require(row_keys == plan_keys, "scaling rows differ from recorded plan")
    timeout = next(row for row in monolithic if row["count"] == 5808)
    require(
        timeout["status"] == "timeout"
        and timeout["completed_declarations"] == 4607,
        "unexpected 5808 timeout result",
    )
    monolithic_summary = [
        ({
            key: row.get(key)
            for key in (
                "count", "status", "declarations", "completed_declarations",
                "wall_seconds", "max_rss_kb", "decl_ms_sum",
                "decl_ms_first", "decl_ms_median", "decl_ms_last",
                "decl_ms_max", "z3_reported_seconds", "rlimit_last",
            )
        } | {
            "status": row.get("status", "success"),
            "completed_declarations":
                row.get("completed_declarations", row["declarations"]),
        })
        for row in sorted(monolithic, key=lambda row: row["count"])
    ]
    split_summary = {
        "groups": len(split),
        "declarations": sum(row["declarations"] for row in split),
        "wall_seconds_sum": sum(row["wall_seconds"] for row in split),
        "wall_seconds_range": [
            min(row["wall_seconds"] for row in split),
            max(row["wall_seconds"] for row in split),
        ],
        "decl_ms_sum": sum(row["decl_ms_sum"] for row in split),
        "z3_reported_seconds_sum": sum(
            row["z3_reported_seconds"] for row in split
        ),
        "max_rss_kb": max(row["max_rss_kb"] for row in split),
        "last_decl_ms_max": max(row["decl_ms_last"] for row in split),
    }

    probes = {row["probe"]: row for row in read_rows(files["probes"])}
    require(
        set(probes) == {"baseline", "no-ambients", "admit", "lax"},
        "probe rows are incomplete",
    )
    probe_plan = {
        item["probe"]: (item["count"], item["options"])
        for item in provenance["probes_provenance"]["probe_plan"]
    }
    for name, row in probes.items():
        require(
            (row["count"], row["options"]) == probe_plan[name],
            f"{name} differs from probe plan",
        )
    scaling_sources = {
        row["count"]: row["source_sha256"]
        for row in monolithic
        if row.get("status", "success") == "success"
    }
    require(
        probes["baseline"]["source_sha256"] == scaling_sources[2048]
        == probes["no-ambients"]["source_sha256"]
        and probes["admit"]["source_sha256"] == scaling_sources[4096]
        == probes["lax"]["source_sha256"],
        "probe sources differ from scaling sources",
    )

    trace_command, trace = parse_events(files["trace_1024"])
    no_ambient_command, no_ambient_trace = parse_events(
        files["trace_no_ambients_1024"]
    )
    flush_command, flush = parse_events(files["flush_trace"])
    no_ambient_flush_command, no_ambient_flush = parse_events(
        files["flush_trace_no_ambients"]
    )
    selected = {}
    for number in (128, 256, 512, 768, 1024):
        if number not in trace.get("PRUNE", {}):
            continue
        prune = trace["PRUNE"][number]
        selected[number] = {
            "prune_ms": prune[0],
            "retained_declarations": int(prune[2]),
            "defs_and_decls": int(prune[3]),
            "trigger_keys": int(prune[5]),
            "trigger_edges": int(prune[6]),
            "assumption_to_triggers": int(prune[7]),
            "assumptions": int(prune[8]),
            "ambients": int(prune[9]),
            "extra_roots": int(prune[10]),
            "ask_ms": trace["ASK"][number][0],
            "z3_ms": int(trace["ASK"][number][1]),
            "solve_ms": trace["SOLVE"][number][0],
            "encode_sig_ms": trace["ENCODE"][number][0],
            "process_decl_ms": trace["TC"][number][0],
            "gamma_sig_before": int(trace["TC"][number][1]),
            "gamma_sig_after": int(trace["TC"][number][2]),
            "gamma_cache_before": int(trace["TC"][number][3]),
            "gamma_cache_after": int(trace["TC"][number][4]),
        }
    selected_no_ambients = {}
    for number in (128, 256, 512, 768, 1024):
        prune = no_ambient_trace["PRUNE"][number]
        selected_no_ambients[number] = {
            "prune_ms": prune[0],
            "retained_declarations": int(prune[2]),
            "ambients": int(prune[9]),
            "extra_roots": int(prune[10]),
            "pruned_ambients": int(prune[11]),
            "ask_ms": no_ambient_trace["ASK"][number][0],
            "z3_ms": int(no_ambient_trace["ASK"][number][1]),
            "solve_ms": no_ambient_trace["SOLVE"][number][0],
            "process_decl_ms": no_ambient_trace["TC"][number][0],
        }
    require(
        provenance["trace_1024_provenance"]["source_sha256"]
        == scaling_sources[1024]
        and provenance["flush_trace_provenance"]["source_sha256"]
        == scaling_sources[512],
        "trace sources differ from scaling sources",
    )

    flush_512 = flush["FLUSH"][512]
    no_ambient_flush_512 = no_ambient_flush["FLUSH"][512]
    phase_512 = {
        "baseline": {
            "pruning_ms": flush["PRUNE"][512][0],
            "filter_sort_ms": flush_512[0] - flush["PRUNE"][512][0],
            "new_declarations_flushed": int(flush_512[2]),
            "given_declaration_names": int(flush_512[3]),
            "z3_ms": int(flush["ASK"][512][1]),
            "serialization_communication_ms":
                flush["ASK"][512][0] - flush_512[0] - flush["ASK"][512][1],
            "query_encoding_ms":
                flush["SOLVE"][512][0] - flush["ASK"][512][0],
            "post_query_encode_sig_ms": flush["ENCODE"][512][0],
            "other_typechecking_ms":
                flush["TC"][512][0]
                - flush["SOLVE"][512][0]
                - flush["ENCODE"][512][0],
        },
        "no_ambients": {
            "pruning_ms": no_ambient_flush["PRUNE"][512][0],
            "filter_sort_ms":
                no_ambient_flush_512[0]
                - no_ambient_flush["PRUNE"][512][0],
            "new_declarations_flushed": int(no_ambient_flush_512[2]),
            "given_declaration_names": int(no_ambient_flush_512[3]),
            "z3_ms": int(no_ambient_flush["ASK"][512][1]),
            "serialization_communication_ms":
                no_ambient_flush["ASK"][512][0]
                - no_ambient_flush_512[0]
                - no_ambient_flush["ASK"][512][1],
            "query_encoding_ms":
                no_ambient_flush["SOLVE"][512][0]
                - no_ambient_flush["ASK"][512][0],
            "post_query_encode_sig_ms":
                no_ambient_flush["ENCODE"][512][0],
            "other_typechecking_ms":
                no_ambient_flush["TC"][512][0]
                - no_ambient_flush["SOLVE"][512][0]
                - no_ambient_flush["ENCODE"][512][0],
        },
    }

    full_no_ambients = read_rows(files["full_no_ambients"])
    require(
        len(full_no_ambients) == 1
        and full_no_ambients[0]["probe"] == "no-ambients"
        and full_no_ambients[0]["query_count"] == 5809,
        "full BV diagnostic is incomplete",
    )
    require(
        provenance["full_no_ambients_provenance"]["probe_plan"]
        == [{
            "probe": "no-ambients",
            "options": ["--ext", "context_pruning_no_ambients"],
        }],
        "full BV diagnostic plan differs",
    )

    worktree_commit = subprocess.check_output(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
    ).strip()
    require(
        worktree_commit == historical_commit,
        "historical worktree moved",
    )
    source = worktree / "tests/micro-benchmarks/BvModelAgreesWithZ3.fst"
    scaling_provenance = provenance["scaling_provenance"]
    full_provenance = provenance["full_no_ambients_provenance"]
    require(
        full_provenance["source_sha256"] == digest(source),
        "full BV source hash differs",
    )

    output = {
        "date": "2026-10-26",
        "question": (
            "What context accumulates across generated squash/equality lemmas, "
            "and is the slowdown BV-specific?"
        ),
        "historical_reference": {
            "source_commit": worktree_commit,
            "recorded_stage2_binary_sha256":
                "0ed8f9746b7796d5f8e91ead8c008cf393f1d03916cba33bbaff0e6a833c792e",
            "report_path": (
                "/home/amosrobinson/.copilot/session-state/"
                "27a5bd47-e213-4805-84c2-84d36719df3e/files/"
                "bv-full3-profile/REPORT.md"
            ),
            "report_access": "restricted by content-exclusion policy",
            "user_supplied_results": {
                "input_cases": 2904,
                "generated_lemmas": 5808,
                "operation_groups": 64,
                "full_plain_seconds": 753,
                "full_timing_seconds": 752,
                "full_query_stats_seconds": 751,
                "split_process_seconds": 152.7,
                "normal_only_seconds": 304,
                "unfolded_only_seconds": 281,
                "lax_combined_seconds": 63,
                "generated_declaration_seconds": 704.1,
                "splice_seconds": 38.2,
                "z3_reported_seconds": 74.2,
            },
        },
        "rebuilt_compiler": {
            "source_commit": worktree_commit,
            "stage2_binary_sha256": scaling_provenance["fstar_sha256"],
            "matches_recorded_binary": False,
            "ocaml": "4.14.2",
            "z3_sha256": scaling_provenance["z3_sha256"],
            "full_source_sha256": digest(source),
        },
        "simple_non_bv_benchmark": {
            "shape": (
                "Distinct top-level let declarations of squash "
                "(opaque refined integer arithmetic equality), with one real "
                "SMT query per declaration and no BV or sequence operations."
            ),
            "monolithic": monolithic_summary,
            "split_5808": split_summary,
            "controlled_probes": probes,
        },
        "context_trace": {
            "baseline": selected,
            "no_ambients": selected_no_ambients,
            "phase_decomposition_at_512": phase_512,
            "commands": {
                "baseline_1024": trace_command,
                "no_ambients_1024": no_ambient_command,
                "baseline_flush_512": flush_command,
                "no_ambients_flush_512": no_ambient_flush_command,
            },
        },
        "full_bv_diagnostic": full_no_ambients[0],
        "growing_structures": {
            "typechecker": (
                "Env.gamma_sig retains one checked sigelt per declaration; "
                "gamma_cache stayed empty in this trace."
            ),
            "normalization": (
                "TypeChecker.Core memo state is cleared before every top-level "
                "declaration and union-find is reset afterward; no growing "
                "normalization cache was observed."
            ),
            "pruning": (
                "Each squash-valued let contributes two HasType(..., squash) "
                "assumptions classified as ambient extra roots. The pruning "
                "maps also grow, but their growth remains when ambients are "
                "excluded without causing the slowdown."
            ),
            "solver_state": (
                "Pruning revisits every ambient/extra root for every query. "
                "SolverState then filters already-given declarations but "
                "in steady state flushes eight newly reachable declarations "
                "per lemma, so its given-name set and persistent Z3 context "
                "grow linearly."
            ),
        },
        "causal_conclusions": [
            (
                "The slowdown is generic to accumulating squash-valued "
                "declarations; the non-BV benchmark reproduces the same "
                "strong order/process-context-associated inflation."
            ),
            (
                "The dominant F* growth is Pruning.prune scanning accumulated "
                "ambient extra roots and resolving their reachable context."
            ),
            (
                "Z3 execution independently grows as eight new declarations "
                "per steady-state lemma remain in its persistent context."
            ),
            (
                "Gamma growth is real but not causal here: with the same "
                "gamma and pruning maps, excluding ambients keeps per-lemma "
                "time nearly flat."
            ),
        ],
        "limitations": [
            (
                "The preserved prior report was inaccessible under content "
                "exclusion; its numerical results are user-supplied."
            ),
            (
                "The rebuilt compiler has the exact historical source commit "
                "but not the recorded binary hash, so the full no-ambient BV "
                "run is diagnostic rather than a matched speedup ratio."
            ),
            (
                "context_pruning_no_ambients is a diagnostic that changes "
                "proof context selection; it is not proposed as a fix."
            ),
            (
                "The attempted no-pruning probe was invalid because this "
                "historical compiler resent duplicate declarations to Z3."
            ),
        ],
        "source_locations": [
            "src/typechecker/FStarC.TypeChecker.Tc.fst:1435-1467",
            "src/typechecker/FStarC.TypeChecker.Env.fst:1608-1618",
            "src/smtencoding/FStarC.SMTEncoding.Encode.fst:635-766,879-1111,2195-2208",
            "src/smtencoding/FStarC.SMTEncoding.Pruning.fst:196-359,608-687",
            "src/smtencoding/FStarC.SMTEncoding.SolverState.fst:243-285,431-490",
            "src/smtencoding/FStarC.SMTEncoding.Z3.fst:620-632",
        ],
        "evidence": {
            name: {"path": str(path), "sha256": digest(path)}
            for name, path in files.items()
        },
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
