# PR #4797 asymptotic complexity review

## Variables

- `R`: expanded module include paths. This includes cache/lib/current-directory
  roots and every root produced by recursive `fstar.include` expansion.
- `I`: command-line include roots before expansion.
- `M`: manifest entries/directories visited while expanding `fstar.include`.
- `Fc`: command-line files used to derive implicit include roots.
- `P`: source path length; `Pr`: one include-root path length.
- `D`: maximum source/include path depth.
- `F`: source files parsed or dependency nodes processed.
- `T`: ranges constructed while parsing/checking.
- `E`: issues rendered; `Q`: positional IDE lookup requests.

String hashing, comparison, normalization, joining, dirname, basename, and
prefix checks are not constant-time; their bounds include the relevant path
lengths. Hash-table access is expected constant bucket access plus string
hash/equality cost.

## Findings

### 1. `source_file_name` retains an `O(R * P)` hot path

`FStarC.Find.source_file_name` first calls cached `find_file`, then normalizes
the resolved absolute path and calls `relative_source_path`
(`src/basic/FStarC.Find.fst:227-286`).

`relative_source_path`:

1. normalizes the filename, `O(P)`;
2. folds over every normalized module include path;
3. allocates `path.dir ^ "/"` and performs a prefix comparison for every root;
4. computes `dirname filename` for each matching flat root;
5. retains the longest match and takes one suffix.

The fold is `O(sum(Pr) + R * P)` in a direct string-cost model, conventionally
`O(R * P)` when root and filename lengths are similarly bounded. It performs
no filesystem calls once the normalized-root cache exists, but it is not
memoized by filename.

`find_file` has a separate exact-string hash cache (`FStarC.Find.fst:25-37,
245-271`). A hot `find_file` avoids filesystem lookup, but it does **not**
avoid the subsequent normalization and full `R`-root scan. Thus repeated
`source_file_name` calls for the same filename remain `O(R * P)`, not expected
`O(1)`.

Cold behavior is more expensive:

- an absolute filename causes one existence check in `do_find`;
- a relative filename can scan all include paths and perform up to `R`
  `file_exists` calls before a miss or lowest-precedence match;
- the successful result is then normalized and all `R` roots are scanned
  again to choose the longest owning root.

The hierarchical semantics inherently require identifying the applicable
root. A linear root scan is reasonable for one uncached filename, but repeating
it for an identical filename is avoidable.

**Simplest semantics-preserving improvement:** cache the final
`source_file_name` result by input string, beside `find_file_cache`, and clear
it in `Find.clear`. The output depends on the same include/cache/file-list
state that already triggers `clear`, so this does not require a new
invalidation model. It changes repeated calls from `O(R * P)` to expected
hash-table lookup cost (including string hashing/equality).

### 2. Ordinary parsing duplicates the root scan per source

`FStarC.Parser.Grammar.start` and `start_with` pass the original filename both
to `Lexer.lex_all` and `Pratt.mk_pstate`
(`src/parser/FStarC.Parser.Grammar.fst:2394-2403`).

The PR changed both entry points:

- `Lexer.lex_all` calls `source_file_name`
  (`src/parser/FStarC.Parser.Lexer.fst:1090-1099`);
- `Pratt.mk_pstate` calls it again
  (`src/parser/FStarC.Parser.Pratt.fst:69-72`).

Therefore ordinary batch parsing adds two `O(R * P)` conversions per file, for
aggregate `O(F * R * P)`. It does **not** add work per token or per range.
`parse_tokens` calls only Pratt; extension-language `parse_lang` has its own
single conversion.

Incremental IDE parsing has one additional conversion per chunk:
`Interactive.Ide.Types.initial_range` converts the REPL filename before
`Incremental.parse_code` passes the original filename to the ordinary
lexer/Pratt pair (`src/interactive/FStarC.Interactive.Ide.Types.fst:46-47`;
`src/interactive/FStarC.Interactive.Incremental.fst:249-259`). That path
therefore performs three conversions per parsed chunk.

The second ordinary-parser conversion is avoidable. A final-result cache in
`Find` removes it for all callers. A narrower alternative is to normalize once
in `Grammar.start`/`start_with` and pass the result to both lexer and Pratt, but
that does not help dependency, IDE, or warning callers.

### 3. Cold include-root construction can be duplicated

`full_include_path` and `module_include_paths_normalized` are distinct lazy
caches (`FStarC.Find.fst:207-225`). On their first use, each independently
calls `module_include_paths`, which recursively reads and expands
`fstar.include` manifests (`FStarC.Find.fst:104-138`).

A first `source_file_name` can initialize both:

1. `find_file` initializes `full_include_path`;
2. `relative_source_path` initializes `module_include_paths_normalized`.

This can traverse the include-manifest structure twice. Expansion of the `I`
explicit roots is `O(I + M + R)` apart from path-string work and filesystem
operations. `module_include_paths` also derives roots for `Fc` command-line
files and tests each against expanded explicit roots. Since
`module_include_covers_path` can walk parent directories, that existing phase
is up to `O(Fc * R * D * P)` in this report's string-cost model, where `D` is
path depth. The normalized cache additionally normalizes all `R` resulting
paths.

This is one-time per option epoch, not per source file. The duplication partly
predates this PR because both caches already existed and dependency module-name
resolution already used normalized roots; the PR makes it reachable directly
from every parser entry. If `Fc` and `R` grow together, this inherited cold
construction can be quadratic in those two collections; the PR duplicates its
constant number of executions rather than adding another nesting level.

This is a cold-start inefficiency rather than a worsening asymptotic bound.
If cold initialization matters, derive both cached representations from one
expanded `module_include_paths` value instead of independently expanding it.
That is a broader change than the filename-result cache and is not necessary
for correctness.

### 4. Dependency generation scales with files times expanded roots

`deps_from_parsing_data` now calls `source_file_name` once per processed file
to build a diagnostic range
(`src/parser/FStarC.Parser.Dep.fst:1519-1533`). Across `F` dependency nodes,
this adds `O(F * R * P)` CPU after root-cache initialization. If each filename
is distinct, a filename-result cache does not remove the first root scan, which
is inherent in mapping each source to its owning include root.

`print_full` calls `source_file_name` only while reporting interfaces without
implementations (`FStarC.Parser.Dep.fst:2636-2651`), not unconditionally for
all dependency output. Its added cost is `O(W * R * P)` for `W` such warnings.

The prior implementation of `module_name_from_include_path` already performed
the same normalize-and-longest-root scan. Moving that logic into
`relative_source_path` is complexity-neutral and removes duplicate source
code. The new diagnostic-range conversion is additional.

The focused measurements in `SOURCE_WORKLOADS.json` are consistent with this
shape: `Bug3207 --dep full` executes 159 conversions; an instrumented run
spends about 4.5 ms in them. This supports the cost model but does not establish
that it explains the CI-wide regression.

### 5. Range construction improves, rather than regresses

`Range.Type.mk_rng` changed from `Filepath.basename file_name` to storing the
input (`src/basic/FStarC.Range.Type.fst:93-97`), and
`Range.Ops.set_file_of_range` made the analogous change.

Worst-case construction changes from `O(P)` to `O(1)` per range, so aggregate
worst-case range filename work changes from `O(T * P)` to `O(T)`.

The base `Filepath.basename` implementation already remembers its most recent
argument by physical equality (`src/basic/FStarC.Filepath-ocaml.fst:43-55`).
When consecutive ranges share the same filename object, the old common-case
cost after the first call was already `O(1)`. The PR still cannot introduce an
asymptotic regression here; it removes basename work and its cache mutation.

Using the precomputed lexer filename for `__SOURCE_FILE__` and
`__FILE_LINE__` also removes per-directive basename calls.

### 6. Diagnostics become cheaper on the common text path

Before the PR, every text issue rendered by `issue_to_doc'` applied
`Range.refind_range`, which resolves both definition and use filenames. The PR
prints stored include-relative names directly
(`src/basic/FStarC.Errors.fst:157-160`).

For `E` text issues, this removes up to `2E` cached lookups,
normalizations, and cold include-path/filesystem searches. Structured JSON
locations still call `refind_range` (`FStarC.Errors.fst:127-133`), preserving
absolute-location behavior where required.

The changed `refind_file` passes the full include-relative path to `find_file`
instead of taking a basename first (`FStarC.Find.fst:329-336`). Its asymptotic
shape remains a cached lookup with up to `R` filesystem probes on a cold
relative key. The longer key/joined path increases string constants but is
inherent in disambiguating hierarchical modules.

The two changed `CheckedFiles` calls invoke `source_file_name` only when
reporting cache-load or cache-write warnings
(`src/fstar/FStarC.CheckedFiles.fst:477-483, 651-662`). For `Wc` such warnings,
the added bound is `O(Wc * R * P)`. These are exceptional paths, not work on
every successful cache read/write.

### 7. IDE lookup adds one conditional conversion, not a nested table scan

`symlookup` first queries the identifier database using the client filename.
Only on a miss does it strip `file://`, call `source_file_name`, and retry
(`src/interactive/FStarC.Interactive.QueryHelper.fst:75-91`).

The identifier database is an AVL map by filename and then row, followed by a
linear scan of column entries on that row
(`FStarC.TypeChecker.Common.fst:136-143, 209-217`;
`FStarC.PSMap.fst`; `FStarC.PIMap.fst`). A miss therefore costs roughly
one of:

- filename-key miss: `O(log Nf * P)`;
- filename hit and row miss: `O(log Nf * P + log Nr)`;
- filename/row hit but no covering identifier:
  `O(log Nf * P + log Nr + C)`.

Here `Nf` is indexed filenames, `Nr` rows in that file, and `C` identifiers on
the selected row. The fallback adds `O(R * P)` filename conversion and repeats
the applicable database lookup.

This is per positional IDE request (`Q`), not per checked identifier. For an
absolute-path client that consistently misses the stored key, aggregate cost
is `O(Q * (R * P + lookup))`. Caching final `source_file_name` results removes
the repeated root scan while preserving the required retry.

## Conclusion

No new operation has accidentally become quadratic in the number of source
ranges or tokens. The high-frequency range constructor became cheaper, and
common text diagnostics also became cheaper. The existing cold include-root
construction can have a cross-product of command-line files and expanded
roots, as described above; the PR can cause that cached construction to be
initialized from more paths but does not add a new nesting level to it.

There is one unexpected repeated linear cost: final source-name conversion is
uncached and ordinary parsing invokes it twice, so hot parsing/IDE/dependency
paths retain `O(R * P)` work per conversion and `O(F * R * P)` aggregate work.
This is a scaling risk for projects with many expanded include roots. It is
avoidable with a solver-option-epoch-local `source_file_name` cache cleared by
`Find.clear`. The first conversion for each distinct source still necessarily
depends on include-root ownership unless the include representation gains a
more specialized path-prefix index.

This complexity finding is not proof that PR #4797 caused the CI's 1.022x
headline. Existing controlled measurements found only a small dependency-path
cost consistent with the analysis, while representative verification
workloads did not reproduce a broad regression.
