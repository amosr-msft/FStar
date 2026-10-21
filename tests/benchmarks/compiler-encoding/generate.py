#!/usr/bin/env python3

import argparse
import hashlib
import json
import random
from pathlib import Path

# These define historical comparability; changing either requires a generator-version bump.
SEED = 20261021
WIDTHS = [1, 1, 1, 1, 4, 8, 16, 32, 64, 128]
INPUT_FIELDS = 50
STATE_FIELDS = 120
OUTPUT_FIELDS = 25
CHILD_CALLS = 10


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
    manifest = {
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
    for representation in ["bv", "uint"]:
        module, source = children_source(representation)
        write_source(args.out_dir, module, source, manifest)
    for count in args.bindings:
        for representation in ["bv", "uint"]:
            module, source = benchmark_source(representation, "direct", count)
            write_source(args.out_dir, module, source, manifest)
    for style in ["refined", "assert"]:
        module, source = benchmark_source("bv", style, max(args.bindings))
        write_source(args.out_dir, module, source, manifest)
    for kind in ["assertions", "refined-assert", "refined", "bv"]:
        module, source = isolation_source(kind, args.isolation_count)
        write_source(args.out_dir, module, source, manifest)
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (args.out_dir / "manifest.json").write_text(manifest_text)


if __name__ == "__main__":
    main()
