#!/usr/bin/env python3

import argparse
from pathlib import Path


HEADER = """module {module}

irreducible
let opaque_param (i:int) : Tot (r:int{{r == i}}) = i

"""


def declarations(start, count):
    return "".join(
        f"let agreement_{i:04d} : squash "
        f"(opaque_param {i} + {i % 17 + 1} == {i + i % 17 + 1}) = ()\n"
        for i in range(start, start + count)
    )


def write_module(path, module, start, count):
    path.write_text(HEADER.format(module=module) + declarations(start, count))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--groups", type=int, default=1)
    args = parser.parse_args()
    if args.count <= 0 or args.groups <= 0 or args.groups > args.count:
        parser.error("--count must be positive and at least --groups")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.groups == 1:
        write_module(
            args.output / f"SimpleAgreement{args.count}.fst",
            f"SimpleAgreement{args.count}",
            0,
            args.count,
        )
        return
    quotient, remainder = divmod(args.count, args.groups)
    start = 0
    for group in range(args.groups):
        group_size = quotient + (1 if group < remainder else 0)
        write_module(
            args.output / f"SimpleAgreement{args.count}G{group:02d}.fst",
            f"SimpleAgreement{args.count}G{group:02d}",
            start,
            group_size,
        )
        start += group_size


if __name__ == "__main__":
    main()
