#!/usr/bin/env python3

import argparse
import hashlib
import json
import random
import re
from pathlib import Path

# These define historical comparability; changing either requires a generator-version bump.
SEED = 20261021
WIDTHS = [1, 1, 1, 1, 4, 8, 16, 32, 64, 128]
INPUT_FIELDS = 50
STATE_FIELDS = 120
OUTPUT_FIELDS = 25
CHILD_CALLS = 10
GENERATOR_VERSION = 2
WIDTH_SET = sorted(set(WIDTHS))


def record_type(name, fields):
    body = ";\n  ".join(f"{field}: {typ}" for field, typ in fields)
    return f"type {name} = {{\n  {body}\n}}\n"


def record_value(fields):
    return "{ " + "; ".join(f"{name} = {value}" for name, value in fields) + " }"


def literal(representation, style, width, value):
    if representation == "bv":
        raw = f"(BV.int2bv #{width} {value})"
        if style == "refined":
            raw = f"(BV.int2bv #{width} ({value} <: U.uint_t {width}))"
        elif style == "assert":
            raw = (
                f"(assert_norm (U.size {value} {width}); "
                f"BV.int2bv #{width} {value})"
            )
        return raw
    raw = f"({value} <: U.uint_t {width})"
    if style == "assert":
        raw = f"(assert_norm (U.size {value} {width}); {raw})"
    return raw


def type_at(representation, width):
    if representation == "bv":
        return f"BV.bv_t {width}"
    return f"U.uint_t {width}"


def children_source(representation):
    cap = "Bv" if representation == "bv" else "UInt"
    module = f"Bench{cap}Children"
    typ = type_at(representation, 8)
    flag_typ = type_at(representation, 1)
    zero8 = literal(representation, "direct", 8, 0)
    one1 = literal(representation, "direct", 1, 1)
    if representation == "bv":
        mixed = "BV.bvxor #8 tr.current.a tr.current.b"
        flag = "BV.bvand #1 tr.current.flag " + one1
    else:
        mixed = "U.logxor #8 tr.current.a tr.current.b"
        flag = "U.logand #1 tr.current.flag " + one1
    source = f"""module {module}

module BV = FStar.BV
module U = FStar.UInt

type input_t = {{
  a: {typ};
  b: {typ};
  flag: {flag_typ}
}}

type transition = {{
  previous: input_t;
  current: input_t
}}

type output_t = {{
  value: {typ};
  flag: {flag_typ}
}}

type step_result = {{
  state: unit;
  output: output_t
}}

let pure_step (tr:transition) (_:unit) : Tot step_result =
  {{ state = (); output = {{ value = {mixed}; flag = {flag} }} }}

let environment_step
  (_:transition)
  (oracle:output_t)
  (_:unit)
  : Tot step_result =
  {{ state = (); output = oracle }}

let zero_output : output_t =
  {{ value = {zero8}; flag = {literal(representation, "direct", 1, 0)} }}
"""
    return module, source


def operation(representation, style, width, index, pools, rng):
    same = pools[width]
    a = rng.choice(same)
    b = rng.choice(same)
    value = rng.randrange(1 << min(width, 20))
    lit = literal(representation, style, width, value)
    flag = rng.choice(pools[1])
    op = index % 10
    if op == 0:
        return f"BV.bvxor #{width} {a} {b}" if representation == "bv" else f"U.logxor #{width} {a} {b}"
    if op == 1:
        return f"BV.bvand #{width} {a} {lit}" if representation == "bv" else f"U.logand #{width} {a} {lit}"
    if op == 2:
        return f"BV.bvor #{width} {a} {b}" if representation == "bv" else f"U.logor #{width} {a} {b}"
    if op == 3:
        return f"BV.bvnot #{width} {a}" if representation == "bv" else f"U.lognot #{width} {a}"
    if op == 4:
        zero = literal(representation, style, 1, 0)
        return f"if {flag} <> {zero} then {a} else {b}"
    if op == 5:
        return f"BV.bvadd #{width} {a} {b}" if representation == "bv" else f"U.add_mod #{width} {a} {b}"
    if op == 6:
        shift = rng.randrange(max(1, width))
        return f"BV.bvshl #{width} {a} {shift}" if representation == "bv" else f"U.shift_left #{width} {a} {shift}"
    if op == 7 and width < 128 and width * 2 in pools:
        source = rng.choice(pools[width * 2])
        if representation == "bv":
            return f"BV.bv_extract #{width * 2} {source} {width - 1} 0"
        return f"U.to_uint_t {width} {source}"
    if op == 8 and width > 1 and width // 2 in pools:
        left = rng.choice(pools[width // 2])
        right = rng.choice(pools[width // 2])
        if representation == "bv":
            return f"BV.bv_concat #{width // 2} #{width // 2} {left} {right}"
        return f"U.to_uint_t {width} ({left} * U.pow2_n #{width} {width // 2} + {right})"
    if op == 9 and width > 1 and width // 2 in pools:
        source = rng.choice(pools[width // 2])
        if representation == "bv":
            return f"BV.bv_repeat #{width // 2} #2 {source}"
        return f"U.to_uint_t {width} ({source} * (U.pow2_n #{width} {width // 2} + 1))"
    return f"BV.bvxor #{width} {a} {lit}" if representation == "bv" else f"U.logxor #{width} {a} {lit}"


def benchmark_source(representation, style, binding_count):
    rng = random.Random(SEED)
    cap = "Bv" if representation == "bv" else "UInt"
    style_cap = style.capitalize()
    module = f"Bench{cap}{style_cap}{binding_count}"
    child_module = f"Bench{cap}Children"
    input_widths = [WIDTHS[i % len(WIDTHS)] for i in range(INPUT_FIELDS)]
    state_widths = [WIDTHS[(i * 7 + 3) % len(WIDTHS)] for i in range(STATE_FIELDS)]
    output_widths = [WIDTHS[(i * 3 + 1) % len(WIDTHS)] for i in range(OUTPUT_FIELDS)]
    input_fields = [(f"x{i}", type_at(representation, width)) for i, width in enumerate(input_widths)]
    state_fields = [(f"s{i}", type_at(representation, width)) for i, width in enumerate(state_widths)]
    state_fields += [(f"child_state{i}", "unit") for i in range(CHILD_CALLS)]
    output_fields = [(f"y{i}", type_at(representation, width)) for i, width in enumerate(output_widths)]
    oracle_fields = [(f"child_output{i}", "C.output_t") for i in range(CHILD_CALLS // 2, CHILD_CALLS)]

    pools = {width: [] for width in sorted(set(WIDTHS))}
    for i, width in enumerate(input_widths):
        pools[width].append(f"tr.current.x{i}")
        pools[width].append(f"tr.previous.x{i}")
    for i, width in enumerate(state_widths[:STATE_FIELDS]):
        pools[width].append(f"st.s{i}")

    lines = [
        f"module {module}",
        "",
        "module BV = FStar.BV",
        "module U = FStar.UInt",
        f"module C = {child_module}",
        "",
        record_type("input_t", input_fields),
        record_type("transition", [("previous", "input_t"), ("current", "input_t")]),
        record_type("oracle_t", oracle_fields),
        record_type("state_t", state_fields),
        record_type("output_t", output_fields),
        "type step_result = {",
        "  state: state_t;",
        "  output: output_t",
        "}",
        "",
        "let step (tr:transition) (oracle:oracle_t) (st:state_t) : Tot step_result =",
    ]

    child_results = []
    eight_inputs = pools[8]
    one_inputs = pools[1]
    for i in range(CHILD_CALLS):
        previous = record_value([
            ("a", rng.choice(eight_inputs)),
            ("b", rng.choice(eight_inputs)),
            ("flag", rng.choice(one_inputs)),
        ])
        current = record_value([
            ("a", rng.choice(eight_inputs)),
            ("b", rng.choice(eight_inputs)),
            ("flag", rng.choice(one_inputs)),
        ])
        lines.append(f"  let child_input{i} : C.transition = {record_value([('previous', previous), ('current', current)])} in")
        if i < CHILD_CALLS // 2:
            lines.append(f"  let child_result{i} = C.pure_step child_input{i} st.child_state{i} in")
        else:
            lines.append(
                f"  let child_result{i} = C.environment_step child_input{i} "
                f"oracle.child_output{i} st.child_state{i} in"
            )
        pools[8].append(f"child_result{i}.output.value")
        pools[1].append(f"child_result{i}.output.flag")
        child_results.append(f"child_result{i}")

    generated = []
    for i in range(binding_count):
        width = WIDTHS[rng.randrange(len(WIDTHS))]
        expr = operation(representation, style, width, i, pools, rng)
        name = f"t{i}"
        lines.append(f"  let {name} : {type_at(representation, width)} = {expr} in")
        pools[width].append(name)
        generated.append((name, width))

    state_values = []
    for i, width in enumerate(state_widths[:STATE_FIELDS]):
        choices = [name for name, candidate_width in generated if candidate_width == width]
        state_values.append((f"s{i}", choices[-1 - (i % min(8, len(choices)))]))
    state_values += [(f"child_state{i}", f"{child_results[i]}.state") for i in range(CHILD_CALLS)]
    output_values = []
    for i, width in enumerate(output_widths):
        choices = [name for name, candidate_width in generated if candidate_width == width]
        output_values.append((f"y{i}", choices[-1 - (i % min(8, len(choices)))]))
    lines.append(
        "  { state = " + record_value(state_values) +
        "; output = " + record_value(output_values) + " }"
    )
    return module, "\n".join(lines) + "\n"


def operation_counts(binding_count):
    named = {
        "conditional": int(binding_count * 0.30 + 0.5),
        "extract": int(binding_count * 0.15 + 0.5),
        "concat": int(binding_count * 0.10 + 0.5),
        "repeat": int(binding_count * 0.05 + 0.5),
        "add": int(binding_count * 0.005 + 0.5),
        "shift": int(binding_count * 0.005 + 0.5),
    }
    named["bitwise"] = binding_count - sum(named.values())
    return named


def make_live_plan(binding_count):
    rng = random.Random(SEED + binding_count)
    counts = operation_counts(binding_count)
    kinds = []
    for kind, count in counts.items():
        kinds.extend([kind] * (count - (len(WIDTH_SET) if kind == "bitwise" else 0)))
    rng.shuffle(kinds)
    kinds = ["bitwise"] * len(WIDTH_SET) + kinds

    input_widths = [WIDTHS[i % len(WIDTHS)] for i in range(INPUT_FIELDS)]
    state_widths = [WIDTHS[(i * 7 + 3) % len(WIDTHS)] for i in range(STATE_FIELDS)]
    external = {width: [] for width in WIDTH_SET}
    for i, width in enumerate(input_widths):
        external[width].extend([f"tr.current.x{i}", f"tr.previous.x{i}"])
    for i, width in enumerate(state_widths):
        external[width].append(f"st.s{i}")
    external[8].extend(f"child_result{i}.output.value" for i in range(CHILD_CALLS))
    external[1].extend(f"child_result{i}.output.flag" for i in range(CHILD_CALLS))

    previous = {}
    bindings = []
    for index, kind in enumerate(kinds):
        if index < len(WIDTH_SET):
            width = WIDTH_SET[index]
        elif kind == "extract":
            width = rng.choice([4, 8, 16, 32, 64])
        elif kind in ("concat", "repeat"):
            width = rng.choice([8, 16, 32, 64, 128])
        else:
            width = rng.choice(WIDTHS)
        anchor = previous.get(width, rng.choice(external[width]))
        deps = [anchor] if re.fullmatch(r"t\d+", anchor) else []
        source_width = width
        if kind == "extract":
            source_width = width * 2
        elif kind in ("concat", "repeat"):
            source_width = width // 2
        binding = {
            "name": f"t{index}",
            "width": width,
            "kind": kind,
            "anchor": anchor,
            "left": rng.choice(external[source_width]),
            "right": rng.choice(external[source_width]),
            "literal": rng.randrange(1 << min(width, 20)),
            "event": ["rising_edge", "reset", "enable"][index % 3],
            "deps": deps,
        }
        bindings.append(binding)
        previous[width] = binding["name"]

    roots = [previous[width] for width in WIDTH_SET]
    graph = graph_metrics(bindings, roots)
    if graph["reachable_bindings"] != binding_count:
        raise RuntimeError("live plan contains unreachable bindings")
    return {
        "bindings": bindings,
        "roots": roots,
        "primary_operations": counts,
        "auxiliary_chain_xors": counts["extract"] + counts["concat"] + counts["repeat"],
        "graph": graph,
    }


def graph_metrics(bindings, roots):
    dependencies = {binding["name"]: binding["deps"] for binding in bindings}
    reachable = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name not in reachable:
            reachable.add(name)
            pending.extend(dependencies[name])
    depths = {}
    for binding in bindings:
        deps = binding["deps"]
        depths[binding["name"]] = 1 + max((depths[name] for name in deps), default=0)
    return {
        "binding_count": len(bindings),
        "reachable_bindings": len(reachable),
        "maximum_dependency_depth": max(depths.values(), default=0),
        "root_bindings": roots,
    }


def sparse_graph_metrics(source):
    bindings = []
    roots = []
    for line in source.splitlines():
        match = re.match(r"\s*let (t\d+) : .* = (.*) in$", line)
        if match:
            bindings.append({
                "name": match.group(1),
                "deps": re.findall(r"\bt\d+\b", match.group(2)),
            })
        elif line.startswith("  { state = "):
            roots = sorted(set(re.findall(r"\bt\d+\b", line)))
    return graph_metrics(bindings, roots)


def live_operation(representation, style, binding):
    width = binding["width"]
    anchor = binding["anchor"]
    left = binding["left"]
    right = binding["right"]
    kind = binding["kind"]
    if kind == "conditional":
        return f"if {binding['event']} then {anchor} else {left}"
    if kind == "extract":
        if representation == "bv":
            core = f"BV.bv_extract #{width * 2} {left} {width - 1} 0"
            return f"BV.bvxor #{width} {anchor} ({core})"
        core = f"U.to_uint_t {width} {left}"
        return f"U.logxor #{width} {anchor} ({core})"
    if kind == "concat":
        if representation == "bv":
            core = f"BV.bv_concat #{width // 2} #{width // 2} {left} {right}"
            return f"BV.bvxor #{width} {anchor} ({core})"
        core = f"U.to_uint_t {width} ({left} * U.pow2_n #{width} {width // 2} + {right})"
        return f"U.logxor #{width} {anchor} ({core})"
    if kind == "repeat":
        if representation == "bv":
            core = f"BV.bv_repeat #{width // 2} #2 {left}"
            return f"BV.bvxor #{width} {anchor} ({core})"
        core = f"U.to_uint_t {width} ({left} * (U.pow2_n #{width} {width // 2} + 1))"
        return f"U.logxor #{width} {anchor} ({core})"
    if kind == "add":
        return f"BV.bvadd #{width} {anchor} {left}" if representation == "bv" else f"U.add_mod #{width} {anchor} {left}"
    if kind == "shift":
        return f"BV.bvshl #{width} {anchor} (BV.bv2int #{width} {left})" if representation == "bv" else f"U.shift_left #{width} {anchor} {left}"
    selector = int(binding["name"][1:]) % 4
    if selector == 0:
        return f"BV.bvxor #{width} {anchor} {left}" if representation == "bv" else f"U.logxor #{width} {anchor} {left}"
    if selector == 1:
        value = literal(representation, style, width, binding["literal"])
        return f"BV.bvand #{width} {anchor} {value}" if representation == "bv" else f"U.logand #{width} {anchor} {value}"
    if selector == 2:
        return f"BV.bvor #{width} {anchor} {left}" if representation == "bv" else f"U.logor #{width} {anchor} {left}"
    return f"BV.bvnot #{width} {anchor}" if representation == "bv" else f"U.lognot #{width} {anchor}"


def live_benchmark_source(representation, binding_count, plan):
    rng = random.Random(SEED)
    cap = "Bv" if representation == "bv" else "UInt"
    module = f"Bench{cap}Live{binding_count}"
    child_module = f"Bench{cap}Children"
    input_widths = [WIDTHS[i % len(WIDTHS)] for i in range(INPUT_FIELDS)]
    state_widths = [WIDTHS[(i * 7 + 3) % len(WIDTHS)] for i in range(STATE_FIELDS)]
    output_widths = [WIDTHS[(i * 3 + 1) % len(WIDTHS)] for i in range(OUTPUT_FIELDS)]
    input_fields = [(f"x{i}", type_at(representation, width)) for i, width in enumerate(input_widths)]
    state_fields = [(f"s{i}", type_at(representation, width)) for i, width in enumerate(state_widths)]
    state_fields += [(f"child_state{i}", "unit") for i in range(CHILD_CALLS)]
    output_fields = [(f"y{i}", type_at(representation, width)) for i, width in enumerate(output_widths)]
    oracle_fields = [(f"child_output{i}", "C.output_t") for i in range(CHILD_CALLS // 2, CHILD_CALLS)]
    zero1 = literal(representation, "direct", 1, 0)
    latest = {binding["width"]: binding["name"] for binding in plan["bindings"]}

    lines = [
        f"module {module}", "", "module BV = FStar.BV", "module U = FStar.UInt",
        f"module C = {child_module}", "",
        record_type("input_t", input_fields),
        record_type("transition", [("previous", "input_t"), ("current", "input_t")]),
        record_type("oracle_t", oracle_fields),
        record_type("state_t", state_fields),
        record_type("output_t", output_fields),
        "type step_result = {", "  state: state_t;", "  output: output_t", "}", "",
        "let step (tr:transition) (oracle:oracle_t) (st:state_t) : Tot step_result =",
        f"  let rising_edge = tr.previous.x0 = {zero1} && tr.current.x0 <> {zero1} in",
        f"  let reset = tr.current.x1 <> {zero1} in",
        f"  let enable = tr.current.x2 <> {zero1} in",
    ]

    eight_inputs = [f"tr.current.x{i}" for i, width in enumerate(input_widths) if width == 8]
    one_inputs = [f"tr.current.x{i}" for i, width in enumerate(input_widths) if width == 1]
    for i in range(CHILD_CALLS):
        previous = record_value([
            ("a", rng.choice(eight_inputs)), ("b", rng.choice(eight_inputs)),
            ("flag", rng.choice(one_inputs)),
        ])
        current = record_value([
            ("a", rng.choice(eight_inputs)), ("b", rng.choice(eight_inputs)),
            ("flag", rng.choice(one_inputs)),
        ])
        lines.append(f"  let child_input{i} : C.transition = {record_value([('previous', previous), ('current', current)])} in")
        if i < CHILD_CALLS // 2:
            lines.append(f"  let child_result{i} = C.pure_step child_input{i} st.child_state{i} in")
        else:
            lines.append(f"  let child_result{i} = C.environment_step child_input{i} oracle.child_output{i} st.child_state{i} in")

    for binding in plan["bindings"]:
        expression = live_operation(representation, "direct", binding)
        lines.append(f"  let {binding['name']} : {type_at(representation, binding['width'])} = {expression} in")

    state_values = []
    for i, width in enumerate(state_widths[:STATE_FIELDS]):
        zero = literal(representation, "direct", width, 0)
        update = f"if rising_edge then (if reset then {zero} else if enable then {latest[width]} else st.s{i}) else st.s{i}"
        state_values.append((f"s{i}", update))
    state_values += [(f"child_state{i}", f"child_result{i}.state") for i in range(CHILD_CALLS)]
    output_values = [(f"y{i}", latest[width]) for i, width in enumerate(output_widths)]
    lines.append("  { state = " + record_value(state_values) + "; output = " + record_value(output_values) + " }")
    return module, "\n".join(lines) + "\n"


def isolation_source(kind, count):
    rng = random.Random(SEED)
    cap = "".join(part.capitalize() for part in kind.split("-"))
    module = f"BenchIsolation{cap}{count}"
    lines = [f"module {module}", "", "module BV = FStar.BV", "module U = FStar.UInt", "", "let check_all () : unit ="]
    for i in range(count):
        width = WIDTHS[rng.randrange(len(WIDTHS))]
        value = rng.randrange(1 << min(width, 20))
        if kind == "assertions":
            lines.append(f"  assert_norm (U.size {value} {width});")
        elif kind == "refined-assert":
            lines.append(
                f"  let v{i} = (assert_norm (U.size {value} {width}); "
                f"({value} <: U.uint_t {width})) in"
            )
        elif kind == "refined":
            lines.append(f"  let v{i} = ({value} <: U.uint_t {width}) in")
        elif kind == "bv":
            lines.append(f"  let v{i} = BV.int2bv #{width} {value} in")
        else:
            raise ValueError(kind)
    lines.append("  ()")
    return module, "\n".join(lines) + "\n"


def write_source(out_dir, module, source, manifest):
    path = out_dir / f"{module}.fst"
    path.write_text(source)
    manifest["sources"][path.name] = {
        "module": module,
        "sha256": hashlib.sha256(source.encode()).hexdigest(),
        "bytes": len(source.encode()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=Path("_generated"))
    parser.add_argument("--bindings", type=int, nargs="+", default=[100, 250, 500, 1000])
    parser.add_argument("--isolation-count", type=int, default=400)
    args = parser.parse_args()
    if not args.bindings or min(args.bindings) < 100:
        parser.error("--bindings requires one or more values of at least 100")
    if args.isolation_count < 1:
        parser.error("--isolation-count must be positive")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    legacy_manifest = {
        "generator_version": 1,
        "seed": SEED,
        "input_fields": INPUT_FIELDS,
        "state_fields": STATE_FIELDS,
        "output_fields": OUTPUT_FIELDS,
        "child_calls": CHILD_CALLS,
        "bindings": args.bindings,
        "isolation_count": args.isolation_count,
        "sources": {},
    }
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "bindings": args.bindings,
        "shapes": {},
        "sources": {},
    }
    for representation in ["bv", "uint"]:
        module, source = children_source(representation)
        write_source(args.out_dir, module, source, legacy_manifest)
        manifest["sources"][f"{module}.fst"] = legacy_manifest["sources"][f"{module}.fst"]
    for count in args.bindings:
        sparse_graph = None
        for representation in ["bv", "uint"]:
            module, source = benchmark_source(representation, "direct", count)
            write_source(args.out_dir, module, source, legacy_manifest)
            manifest["sources"][f"{module}.fst"] = legacy_manifest["sources"][f"{module}.fst"]
            sparse_graph = sparse_graph_metrics(source)
        manifest["shapes"][f"sparse-{count}"] = {
            "label": "sparse_reachability_control",
            "graph": sparse_graph,
        }

        plan = make_live_plan(count)
        plan_text = json.dumps(plan["bindings"], sort_keys=True, separators=(",", ":"))
        for representation in ["bv", "uint"]:
            module, source = live_benchmark_source(representation, count, plan)
            write_source(args.out_dir, module, source, manifest)
        manifest["shapes"][f"live-{count}"] = {
            "label": "representative_live_workload",
            "plan_sha256": hashlib.sha256(plan_text.encode()).hexdigest(),
            "primary_operations": plan["primary_operations"],
            "auxiliary_chain_xors": plan["auxiliary_chain_xors"],
            "graph": plan["graph"],
        }
    for style in ["refined", "assert"]:
        module, source = benchmark_source("bv", style, max(args.bindings))
        write_source(args.out_dir, module, source, legacy_manifest)
        manifest["sources"][f"{module}.fst"] = legacy_manifest["sources"][f"{module}.fst"]
    for kind in ["assertions", "refined-assert", "refined", "bv"]:
        module, source = isolation_source(kind, args.isolation_count)
        write_source(args.out_dir, module, source, legacy_manifest)
        manifest["sources"][f"{module}.fst"] = legacy_manifest["sources"][f"{module}.fst"]
    (args.out_dir / "manifest.json").write_text(json.dumps(legacy_manifest, indent=2, sort_keys=True) + "\n")
    (args.out_dir / "manifest-v2.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
