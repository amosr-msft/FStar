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
// threads to pump the SMT solver subprocess's output; see the subprocess
// section below for how that one use is served without real threads.
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
// double, and stdint's Str_conv builds to_string out of repeated div/rem
// compared with OCaml's generic comparison, which treats a number and a BigInt
// as different shapes (see below).
//
// The wider types are only ever constructed -- Stdint.IntN.one / max_int /
// min_int are module-level bindings, so their constructors run at
// initialisation -- and use BigInt so the 64- and 128-bit constants are exact.
// Cross-width conversions are not provided: they would have to bridge the two
// representations, and nothing reaches them.
//
// On mixing the two representations: js_of_ocaml's caml_compare_val classifies
// a BigInt as an abstract value and compares it with <, > and !==, which are
// value-correct between two BigInts. What is not value-correct is comparing a
// BigInt against a plain number: the tags differ, so the result is decided by
// tag order rather than by magnitude. Keeping each width to a single
// representation is what avoids that.
//
// Whether any wide-stdint value reaches a comparison at all was checked by
// instrumenting caml_compare_val and caml_hash to report BigInt operands, over
// lang-co3's export_json_exe suite and over fstar_co3 typechecking Co3 modules.
// No stdint value reached either. The BigInts that do arrive there are zarith's
// (Prims.int is Z.t), from FStarC.TypeChecker.Primops.division_modulus_op and
// from Z.of_substring. FStarC.Hash is not among them: its hash_code is a plain
// OCaml int.

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
// Arithmetic is provided for these widths because stdint's own initialisation
// uses it: FStar_UInt64.ones is Uint64.pred zero, which is `sub x one`, and
// Str_conv builds each width's constants by repeated mul/add when parsing and
// div/rem when printing. Results are wrapped so they match the C stubs'
// two's-complement behaviour. BigInt is used because the constants exceed the
// exact range of a double.
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
// Queried for diagnostics and for naming temporary files.
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

// --- unix, subprocesses ----------------------------------------------------
// Enough of Unix's process API to run the SMT solver: FStarC.Util keeps one
// long-lived solver, writes a query to its stdin, and reads its stdout until a
// marker line. That needs a pipe whose reads *block*, which is the whole
// difficulty here.
//
// Node's own child pipes cannot do it. The fds behind child_process.spawn are
// non-blocking, so fs.readSync on one fails with EAGAIN as soon as the child
// has not answered yet -- and F*'s reader is an ordinary input_line that
// expects to wait. A named FIFO does block, so a pipe here is a FIFO in a
// per-process temporary directory, handed to js_of_ocaml's own MlNodeFd (which
// already recognises isFIFO() and refuses to seek on it).
//
// Opening a FIFO blocks until the other end is opened, which orders everything
// below. Both ends cannot be opened before the child exists, so caml_unix_pipe
// only creates the FIFO, and the fd is opened on first use; by then the child
// is running and its end is open. The child's ends are opened by a shell doing
// the redirections, in the order the shell performs them (stdin, stdout,
// stderr), so caml_unix_spawn opens the parent's ends in that same order. Any
// other order deadlocks: each side waits for the other on a different FIFO.
//
// This is not a general Unix emulation. It covers the one shape F*'s solver
// driver uses -- create three pipes, spawn one child on them, read until a
// marker, kill and restart -- and each function below says where it departs
// from POSIX.

//Provides: fstar_proc_state
var fstar_proc_state = {
  dir: null,      // per-process temporary directory holding the FIFOs
  seq: 0,         // FIFO counter, for unique names
  children: {},   // pid -> { child, status } for waitpid/kill
};

// Creates the temporary directory on first use and arranges for it to be
// removed on exit, including on an uncaught exception or a signal, so a run
// that dies mid-query does not leave FIFOs behind.
//Provides: fstar_proc_dir
//Requires: fstar_proc_state
function fstar_proc_dir() {
  if (fstar_proc_state.dir) return fstar_proc_state.dir;
  var fs = require("node:fs"), os = require("node:os"), path = require("node:path");
  var dir = fs.mkdtempSync(path.join(os.tmpdir(), "fstar-jsoo-"));
  fstar_proc_state.dir = dir;
  var cleanup = function () {
    for (var pid in fstar_proc_state.children) {
      try { fstar_proc_state.children[pid].child.kill("SIGKILL"); } catch (e) {}
    }
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) {}
  };
  var p = globalThis.process;
  p.on("exit", cleanup);
  // 'exit' does not run for these, so handle them too, then re-raise by
  // restoring the default disposition.
  ["SIGINT", "SIGTERM", "SIGHUP"].forEach(function (sig) {
    var handler = function () {
      cleanup();
      // Remove this listener before re-signalling, or the signal is delivered
      // back to it and the process never terminates.
      p.removeListener(sig, handler);
      p.kill(p.pid, sig);
    };
    p.on(sig, handler);
  });
  p.on("uncaughtException", function (e) {
    cleanup();
    console.error(e && e.stack ? e.stack : String(e));
    p.exit(1);
  });
  return dir;
}

// A FIFO end. The fd is opened lazily (see the note above on ordering); until
// then every operation that needs it forces the open.
//Provides: MlFifoEnd
//Requires: fstar_proc_dir, MlNodeFd, fstar_run_deferred_thread
function MlFifoEnd(fifo_path, mode) {
  this.fifo_path = fifo_path;
  this.mode = mode;   // "r" or "w"
  this.impl = null;   // MlNodeFd, once opened
  this.closed = false;
  this.peer = null;   // the other end of the same FIFO
  this.given_to_child = false;
  this.pending = null;    // bytes select consumed, not yet handed to a read
  this.nb_fd = -1;        // non-blocking view of the same FIFO, for select
  // Read by caml_ml_open_descriptor_out. Buffered: a query is written a piece
  // at a time and is several hundred lines, so writing through would cost a
  // syscall per piece. FStarC.Util flushes before waiting for an answer, so
  // nothing is held back past the point the solver needs it.
  this.flags = { noSeek: true, buffered: 1, wronly: mode === "w" ? 1 : 0 };
}
// A FIFO has no position; channels ask for one when they are created.
MlFifoEnd.prototype.pos = function () { return 0; };
MlFifoEnd.prototype.force = function () {
  if (this.impl) return this.impl;
  var fs = require("node:fs");
  // Opening a FIFO for reading waits for a writer, and for writing waits for a
  // reader. That pairs up correctly with a child, but not when both ends stay
  // here: FStarC.Util's signal pipe is written and read by this process alone,
  // and whichever end opened first would wait for the other. Opening such a
  // pipe read-write completes immediately and satisfies both. The cost is that
  // it never reports end-of-file, since this process is always a writer, which
  // is only acceptable because nothing reads a self-pipe past the byte it
  // expects. A pipe with a child end keeps the plain mode, so end-of-file still
  // reports the solver exiting.
  //
  // Two limits follow. Which pipe is which is decided at first open, so a pipe
  // opened before being handed to a child is treated as local and keeps an
  // internal writer, and would then never report that child's end-of-file. And
  // an open that is waiting for a child cannot be interrupted, because the
  // event loop is blocked: a child that dies between being spawned and opening
  // its redirections leaves this side waiting.
  var self_pipe = !this.given_to_child && !(this.peer && this.peer.given_to_child);
  var mode = (this.mode === "r" && self_pipe) ? "r+" : this.mode;
  var fd = fs.openSync(this.fifo_path, mode);
  this.impl = new MlNodeFd(fd, { noSeek: true, rdonly: this.mode === "r" ? 1 : 0 });
  return this.impl;
};
MlFifoEnd.prototype.read = function (a, off, len, raise_unix) {
  // FStarC.Util waits for the reader by blocking on a one-byte pipe that only
  // the reader writes. On a single thread that would deadlock, so a read that
  // is about to block is the point at which the deferred reader is run: it
  // fills this pipe, and the read then finds its byte. Running it here rather
  // than at Thread.create keeps the observable order (write query, then read
  // answer) identical to the threaded version.
  // select has to consume to find out whether anything is there (see below),
  // so hand back what it took before reading any more.
  if (this.pending && this.pending.length) {
    var k = Math.min(len, this.pending.length);
    for (var i = 0; i < k; i++) a[off + i] = this.pending[i];
    this.pending = this.pending.subarray(k);
    return k;
  }
  var impl = this.force();
  fstar_run_deferred_thread();
  return impl.read(a, off, len, raise_unix);
};
MlFifoEnd.prototype.write = function (buf, off, len, raise_unix) {
  try {
    return this.force().write(buf, off, len, raise_unix);
  } catch (e) {
    // A solver that has already exited leaves no reader. On a real pipe the
    // bytes would sit in the kernel buffer and the writer would not notice, so
    // report them written; the caller then learns of the exit from the
    // end-of-file on the read side, which is the path it handles.
    if (e && (e.code === "EPIPE" || String(e).indexOf("EPIPE") >= 0)) return len;
    throw e;
  }
};
MlFifoEnd.prototype.close = function (raise_unix) {
  if (this.closed) return 0;
  this.closed = true;
  // An end that was never forced has no fd to close; not opening it is what
  // lets the parent drop the child's ends without blocking on the open.
  if (this.impl) { try { this.impl.close(raise_unix); } catch (e) {} }
  if (this.nb_fd >= 0) {
    try { require("node:fs").closeSync(this.nb_fd); } catch (e) {}
    this.nb_fd = -1;
  }
  return 0;
};
MlFifoEnd.prototype.length = function () { return 0; };
MlFifoEnd.prototype.seek = function () { return 0; };
MlFifoEnd.prototype.isatty = function () { return 0; };
MlFifoEnd.prototype.stat = function () {
  // Reported as a FIFO so callers that ask do not treat it as seekable.
  return { kind: 3, size: 0 };
};
// in_channel_of_descr / out_channel_of_descr refuse descriptors that are not
// stream-like. A FIFO is, and answering without forcing the open keeps the
// channel available before the child exists.
MlFifoEnd.prototype.check_stream_semantics = function (cmd) { return 0; };

//Provides: caml_unix_pipe
//Requires: fstar_proc_dir, fstar_proc_state, MlFifoEnd, caml_sys_fds
function caml_unix_pipe(cloexec, vunit) {
  var cp = require("node:child_process");
  var p = fstar_proc_dir() + "/fifo" + fstar_proc_state.seq++;
  cp.execFileSync("mkfifo", [p]);
  var rf = new MlFifoEnd(p, "r"), wf = new MlFifoEnd(p, "w");
  rf.peer = wf; wf.peer = rf;
  var r = caml_sys_fds.length;
  caml_sys_fds[r] = { file: rf };
  var w = caml_sys_fds.length;
  caml_sys_fds[w] = { file: wf };
  return [0, r, w];
}

// The child inherits nothing here: caml_unix_spawn passes the FIFO paths to a
// shell instead of passing fds, so close-on-exec has nothing to act on.
//Provides: caml_unix_set_close_on_exec
function caml_unix_set_close_on_exec(fd) { return 0; }
//Provides: caml_unix_clear_close_on_exec
function caml_unix_clear_close_on_exec(fd) { return 0; }

// Duplicates the descriptor, not the open file: both entries name the same
// FIFO end, which is all the callers here need.
//Provides: caml_unix_dup
//Requires: caml_sys_fds, caml_unix_lookup_file
function caml_unix_dup(cloexec, fd) {
  var file = caml_unix_lookup_file(fd, "dup");
  var n = caml_sys_fds.length;
  caml_sys_fds[n] = { file: file };
  return n;
}

// Spawns via a shell that redirects from the FIFO paths, rather than by
// passing file descriptors, because a descriptor cannot cross into a Node
// child. The parent's ends are then opened in the shell's redirection order
// (stdin, stdout, stderr); opening them in any other order deadlocks.
//
// Departs from POSIX in that the child is a shell, so prog and args are
// quoted rather than exec'd directly, and a missing prog is reported by the
// shell's exit status rather than by ENOENT from spawn.
//Provides: caml_unix_spawn
//Requires: fstar_proc_state, caml_unix_lookup_file, caml_jsstring_of_string, caml_raise_system_error
function caml_unix_spawn(prog, args, optenv, usepath, redirections) {
  var cp = require("node:child_process");
  var shq = function (s) { return "'" + String(s).replace(/'/g, "'\\''") + "'"; };
  // redirections is an OCaml array of the child's three descriptors, tag first.
  var ends = [1, 2, 3].map(function (i) {
    var f = caml_unix_lookup_file(redirections[i], "spawn");
    if (!f.fifo_path) caml_raise_system_error(1, "EINVAL", "spawn");
    f.given_to_child = true;
    return f;
  });
  var cmd = shq(caml_jsstring_of_string(prog));
  // args carries argv[0], which the shell supplies itself.
  for (var i = 2; i < args.length; i++) cmd += " " + shq(caml_jsstring_of_string(args[i]));
  cmd += " <" + shq(ends[0].fifo_path) +
         " >" + shq(ends[1].fifo_path) +
         " 2>" + shq(ends[2].fifo_path);

  var env = undefined;
  if (optenv && optenv !== 0) {
    env = {};
    var a = optenv[1];
    for (var k = 1; k < a.length; k++) {
      var kv = caml_jsstring_of_string(a[k]), eq = kv.indexOf("=");
      if (eq > 0) env[kv.slice(0, eq)] = kv.slice(eq + 1);
    }
  }
  // detached so the shell and the solver share a process group we can signal
  // as a unit; the shell exec's the solver, so killing the group kills it.
  var child = cp.spawn("/bin/sh", ["-c", "exec " + cmd],
                       { stdio: "ignore", detached: true, env: env });
  fstar_proc_state.children[child.pid] = { child: child, status: null };
  child.on("exit", function (code, signal) {
    var e = fstar_proc_state.children[child.pid];
    if (e) e.status = signal ? [1, 0] : [0, code === null ? 0 : code];
  });
  // The descriptors passed here are the child's ends, which the shell opens.
  // This process must open the opposite end of each, or both sides open the
  // same direction and neither completes. The shell performs its redirections
  // left to right, so match that order.
  ends[0].peer.force(); ends[1].peer.force(); ends[2].peer.force();
  return child.pid;
}

// Only the blocking form is supported, and it reports an exit status that was
// observed while the event loop last ran. Node delivers 'exit' asynchronously,
// so a child that has already been killed may not have been reaped yet; report
// it as exited rather than blocking the single thread forever waiting for a
// callback that cannot run.
//Provides: caml_unix_waitpid
//Requires: fstar_proc_state
function caml_unix_waitpid(flags, pid) {
  var e = fstar_proc_state.children[pid];
  if (e && e.status) { delete fstar_proc_state.children[pid]; return [0, pid, e.status]; }
  if (e) delete fstar_proc_state.children[pid];
  return [0, pid, [0, 0]];   // WEXITED 0
}

//Provides: caml_unix_kill
//Requires: fstar_proc_state, caml_raise_system_error
function caml_unix_kill(pid, signum) {
  var e = fstar_proc_state.children[pid];
  if (!e) caml_raise_system_error(1, "ESRCH", "kill");
  try {
    // Negative pid signals the whole group, so the shell and the solver both go.
    globalThis.process.kill(-pid, "SIGKILL");
  } catch (err) {
    try { e.child.kill("SIGKILL"); } catch (e2) {}
  }
  return 0;
}

// Only the zero-timeout poll of a single read descriptor is supported, which is
// how FStarC.Util drains the solver's stderr without blocking. Any use of the
// write or except sets, or a non-zero timeout, is refused rather than answered
// wrongly.
//
// There is no way to ask how much a FIFO has buffered -- fstat reports zero and
// a zero-length read succeeds either way -- so readiness is decided by actually
// reading. A second descriptor on the same FIFO, opened non-blocking, shares
// its buffer and so reports EAGAIN exactly when there is nothing there. What it
// takes is held on the descriptor and handed to the next read, so consuming
// here is not observable.
//Provides: caml_unix_select
//Requires: caml_unix_lookup_file, caml_raise_system_error
function caml_unix_select(rfds, wfds, efds, timeout) {
  if (wfds !== 0 || efds !== 0 || timeout > 0)
    caml_raise_system_error(1, "EINVAL", "select");
  var ready = 0;
  if (rfds !== 0) {
    var fd = rfds[1];
    var file = caml_unix_lookup_file(fd, "select");
    if (file.fifo_path) {
      if (!file.pending || !file.pending.length) {
        var fs = require("node:fs");
        try {
          if (file.nb_fd < 0) {
            file.nb_fd = fs.openSync(file.fifo_path,
                                     fs.constants.O_RDONLY | fs.constants.O_NONBLOCK);
          }
          var buf = new Uint8Array(8192);
          var n = fs.readSync(file.nb_fd, buf, 0, 8192, null);
          if (n > 0) file.pending = buf.subarray(0, n);
        } catch (err) { /* EAGAIN: nothing buffered */ }
      }
      if (file.pending && file.pending.length) ready = [0, fd, 0];
    }
  }
  return [0, ready === 0 ? 0 : ready, 0, 0];
}

// --- threads, for the solver's reader ---------------------------------------
// FStarC.Util reads the solver's answer on a second thread and waits for it by
// blocking on a one-byte pipe, because a signal arriving during Thread.join
// would otherwise be held until the query finished.
//
// A single-threaded host cannot run the two concurrently, but it does not need
// to: the reader only has work once the query has been written, and the writer
// does nothing after writing except wait for the reader. So the thread is
// deferred -- caml_thread_new records the closure, and the blocking read that
// was meant to wait for the reader runs it instead. The observable order is the
// same, and Thread.join then has nothing left to wait for.
//
// This is not a threading implementation. It supports one pending closure at a
// time and runs it at a point the caller chose for other reasons; anything that
// needs two runnable threads at once will not work.
//Provides: fstar_deferred_thread
var fstar_deferred_thread = { pending: null, next_id: 1 };

//Provides: caml_thread_new
//Requires: fstar_deferred_thread
//Requires: caml_failwith
function caml_thread_new(clos) {
  if (fstar_deferred_thread.pending)
    caml_failwith("caml_thread_new: only one deferred thread is supported");
  fstar_deferred_thread.pending = clos;
  return fstar_deferred_thread.next_id++;
}

//Provides: fstar_run_deferred_thread
//Requires: fstar_deferred_thread, caml_callback
function fstar_run_deferred_thread() {
  var clos = fstar_deferred_thread.pending;
  if (!clos) return 0;
  fstar_deferred_thread.pending = null;
  caml_callback(clos, [0]);
  return 1;
}

//Provides: caml_thread_join
//Requires: fstar_run_deferred_thread
function caml_thread_join(t) { fstar_run_deferred_thread(); return 0; }

//Provides: caml_thread_uncaught_exception
function caml_thread_uncaught_exception(exn) { return 0; }
