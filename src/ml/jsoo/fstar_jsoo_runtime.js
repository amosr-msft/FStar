// js_of_ocaml runtime support for building fstar.exe (and clients of the
// fstarcompiler library) as JavaScript.
//
// These stand in for C stubs with no JavaScript implementation in the
// js_of_ocaml runtime. zarith is supplied separately by the zarith_stubs_js
// library; mtime supplies its own via its META. What remains is stdint, the
// threads initialiser, and two Unix calls.
//
// Anything not implemented here is left to js_of_ocaml, which emits a stub that
// throws, so a path that starts depending on a missing primitive fails at the
// call site rather than silently computing the wrong answer.

// --- threads ---------------------------------------------------------------
// The threads library's initialiser runs at startup. FStarC.Util only creates
// threads to pump the SMT solver subprocess's output; a JavaScript build cannot
// spawn the solver anyway, and caml_thread_new is left unimplemented so that
// attempting to do so fails loudly.
//Provides: caml_thread_initialize
function caml_thread_initialize(unit) { return 0; }

// --- unix ------------------------------------------------------------------
// js_of_ocaml implements most of Unix; these two are missing.
// FStarC.Filepath uses realpath to canonicalise paths and to decide whether two
// paths name the same file, so an approximation that ignores symlinks would
// give wrong module identities.
//Provides: caml_unix_realpath
//Requires: caml_jsstring_of_string, caml_string_of_jsstring, caml_raise_sys_error
function caml_unix_realpath(path) {
  var p = caml_jsstring_of_string(path);
  if (typeof require === "function") {
    return caml_string_of_jsstring(require("node:fs").realpathSync(p));
  }
  caml_raise_sys_error(p + ": realpath is unavailable outside Node");
}
// umask is only consulted when creating directories; the default is fine.
//Provides: caml_unix_umask
function caml_unix_umask(mask) { return 0; }

// --- stdint ----------------------------------------------------------------
// FStar_UInt32 and friends are Stdint.UintN, whose every operation is an
// `external`. stdint is implemented entirely in C and has no JavaScript runtime.
//
// uint32 is the width whose arithmetic is actually reachable, so it is
// represented as a plain JS number: every uint32 is exactly representable as a
// double, and OCaml structural comparison (which stdint's Str_conv uses when
// building to_string out of repeated div/rem) works on numbers but not on
// BigInt under js_of_ocaml. Its full uint32 external surface is implemented.
//
// The wider types are only ever constructed -- Stdint.IntN.one / max_int /
// min_int are module-level bindings, so their constructors run at
// initialisation -- and use BigInt so the 64- and 128-bit constants are exact.
// Cross-width conversions are not provided: they would have to bridge the two
// representations, and nothing reaches them.

//Provides: fstar_stdint_wrap
function fstar_stdint_wrap(v, bits, signed) {
  var m = 1n << BigInt(bits);
  var r = BigInt(v) % m;
  if (r < 0n) r += m;
  if (signed && r >= (m >> 1n)) r -= m;
  return r;
}

// init_custom_ops registers custom-block operations with the OCaml runtime.
// There are no custom blocks here, so there is nothing to register.
//Provides: int128_init_custom_ops
function int128_init_custom_ops() { return 0; }
//Provides: uint128_init_custom_ops
function uint128_init_custom_ops() { return 0; }
//Provides: uint32_init_custom_ops
function uint32_init_custom_ops() { return 0; }
//Provides: uint64_init_custom_ops
function uint64_init_custom_ops() { return 0; }

//Provides: uint32_of_int
function uint32_of_int(i) { return i >>> 0; }
//Provides: uint32_of_float
function uint32_of_float(f) { return (f | 0) >>> 0; }
//Provides: int_of_uint32
function int_of_uint32(x) { return x; }
//Provides: float_of_uint32
function float_of_uint32(x) { return x; }
//Provides: uint32_max_int
function uint32_max_int() { return 4294967295; }
//Provides: uint32_add
function uint32_add(a, b) { return (a + b) >>> 0; }
//Provides: uint32_sub
function uint32_sub(a, b) { return (a - b) >>> 0; }
//Provides: uint32_mul
function uint32_mul(a, b) { return Math.imul(a, b) >>> 0; }
//Provides: uint32_div
//Requires: caml_raise_zero_divide
function uint32_div(a, b) {
  if (b === 0) caml_raise_zero_divide();
  return Math.floor(a / b) >>> 0;
}
//Provides: uint32_mod
//Requires: caml_raise_zero_divide
function uint32_mod(a, b) {
  if (b === 0) caml_raise_zero_divide();
  return (a % b) >>> 0;
}
//Provides: uint32_neg
function uint32_neg(a) { return (-a) >>> 0; }
//Provides: uint32_and
function uint32_and(a, b) { return (a & b) >>> 0; }
//Provides: uint32_or
function uint32_or(a, b) { return (a | b) >>> 0; }
//Provides: uint32_xor
function uint32_xor(a, b) { return (a ^ b) >>> 0; }
//Provides: uint32_shift_left
function uint32_shift_left(a, n) { return (a << n) >>> 0; }
//Provides: uint32_shift_right
function uint32_shift_right(a, n) { return a >>> n; }

//Provides: int40_of_int
//Requires: fstar_stdint_wrap
function int40_of_int(i) { return fstar_stdint_wrap(i, 40, true); }
//Provides: int48_of_int
//Requires: fstar_stdint_wrap
function int48_of_int(i) { return fstar_stdint_wrap(i, 48, true); }
//Provides: int56_of_int
//Requires: fstar_stdint_wrap
function int56_of_int(i) { return fstar_stdint_wrap(i, 56, true); }
//Provides: int128_of_int
//Requires: fstar_stdint_wrap
function int128_of_int(i) { return fstar_stdint_wrap(i, 128, true); }
//Provides: uint40_of_int
//Requires: fstar_stdint_wrap
function uint40_of_int(i) { return fstar_stdint_wrap(i, 40, false); }
//Provides: uint48_of_int
//Requires: fstar_stdint_wrap
function uint48_of_int(i) { return fstar_stdint_wrap(i, 48, false); }
//Provides: uint56_of_int
//Requires: fstar_stdint_wrap
function uint56_of_int(i) { return fstar_stdint_wrap(i, 56, false); }
//Provides: uint64_of_int
//Requires: fstar_stdint_wrap
function uint64_of_int(i) { return fstar_stdint_wrap(i, 64, false); }
// uint64 arithmetic is reachable: FStar_UInt64 is Stdint.Uint64, and the
// compiler's hashing (FStarC.Hash) accumulates into it. BigInt is used because
// uint64 values exceed the exact range of a double; the results are wrapped so
// they match the C stubs' two's-complement behaviour.
//Provides: uint64_add
//Requires: fstar_stdint_wrap
function uint64_add(a, b) { return fstar_stdint_wrap(a + b, 64, false); }
//Provides: uint64_sub
//Requires: fstar_stdint_wrap
function uint64_sub(a, b) { return fstar_stdint_wrap(a - b, 64, false); }
//Provides: uint64_mul
//Requires: fstar_stdint_wrap
function uint64_mul(a, b) { return fstar_stdint_wrap(a * b, 64, false); }
//Provides: uint64_div
//Requires: fstar_stdint_wrap, caml_raise_zero_divide
function uint64_div(a, b) {
  if (b === 0n) caml_raise_zero_divide();
  return fstar_stdint_wrap(a / b, 64, false);
}
//Provides: uint64_mod
//Requires: fstar_stdint_wrap, caml_raise_zero_divide
function uint64_mod(a, b) {
  if (b === 0n) caml_raise_zero_divide();
  return fstar_stdint_wrap(a % b, 64, false);
}
//Provides: uint128_of_int
//Requires: fstar_stdint_wrap
function uint128_of_int(i) { return fstar_stdint_wrap(i, 128, false); }

//Provides: int40_max_int
function int40_max_int() { return (1n << 39n) - 1n; }
//Provides: int40_min_int
function int40_min_int() { return -(1n << 39n); }
//Provides: int48_max_int
function int48_max_int() { return (1n << 47n) - 1n; }
//Provides: int48_min_int
function int48_min_int() { return -(1n << 47n); }
//Provides: int56_max_int
function int56_max_int() { return (1n << 55n) - 1n; }
//Provides: int56_min_int
function int56_min_int() { return -(1n << 55n); }
//Provides: int128_max_int
function int128_max_int() { return (1n << 127n) - 1n; }
//Provides: int128_min_int
function int128_min_int() { return -(1n << 127n); }
//Provides: uint64_max_int
function uint64_max_int() { return (1n << 64n) - 1n; }
//Provides: uint128_max_int
function uint128_max_int() { return (1n << 128n) - 1n; }

// --- unix, process information ---------------------------------------------
// Queried for diagnostics and for naming temporary files. The subprocess calls
// (spawn, pipe, waitpid, kill, select, dup, set_close_on_exec) are deliberately
// left unimplemented: a JavaScript build cannot run the SMT solver, and a
// throwing stub reports that at the call site.
//Provides: caml_unix_getpid
function caml_unix_getpid(unit) {
  return (typeof globalThis.process === "object" && globalThis.process.pid)
    ? globalThis.process.pid : 0;
}
//Provides: caml_unix_gethostname
//Requires: caml_string_of_jsstring
function caml_unix_gethostname(unit) {
  var h = "localhost";
  try { if (typeof require === "function") h = require("node:os").hostname(); } catch (e) {}
  return caml_string_of_jsstring(h);
}
//Provides: caml_unix_putenv
//Requires: caml_jsstring_of_string
function caml_unix_putenv(name, value) {
  var p = globalThis.process;
  if (typeof p === "object" && p.env) {
    p.env[caml_jsstring_of_string(name)] = caml_jsstring_of_string(value);
  }
  return 0;
}
//Provides: caml_unix_lockf
function caml_unix_lockf(fd, cmd, len) { return 0; }
//Provides: caml_unix_sigprocmask
function caml_unix_sigprocmask(mode, mask) { return 0; }
//Provides: caml_thread_yield
function caml_thread_yield(unit) { return 0; }
//Provides: caml_thread_self
function caml_thread_self(unit) { return 0; }
//Provides: caml_thread_id
function caml_thread_id(t) { return 0; }
