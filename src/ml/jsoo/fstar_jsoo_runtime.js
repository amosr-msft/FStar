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


// --- unix, subprocesses -----------------------------------------------------
// Enough of Unix's process API to run the SMT solver. FStarC.Util keeps one
// long-lived solver, writes a query to its stdin, and reads its stdout until a
// marker line; that read has to block, which is the whole difficulty.
//
// Node cannot block on a child's output from the thread that owns the event
// loop: the descriptors behind child_process.spawn are non-blocking, so a
// synchronous read fails with EAGAIN whenever the solver has not answered yet,
// and the callbacks that would deliver the answer cannot run while that thread
// is blocked. So the solver is owned by a worker thread, which is free to use
// ordinary asynchronous stream handlers, and this thread blocks on
// Atomics.wait until the worker publishes a reply into shared memory.
//
// Requests travel by postMessage and replies through the SharedArrayBuffer,
// not the reverse: a reply has to reach a thread that is blocked, which only
// shared memory can do, while a request is posted just before blocking and is
// picked up by a worker whose event loop is running.
//
// Nothing here is a general Unix emulation. It covers the one shape F*'s
// solver driver uses -- create three pipes, spawn one child on them, read
// until a marker, kill and restart -- and each function below says where it
// departs from POSIX.

// Offsets into the control array. DATA is a byte offset into the same buffer.
//Provides: fstar_bridge_layout
var fstar_bridge_layout = { READY: 0, STATUS: 1, LENGTH: 2, DATA: 64, SIZE: 8 << 20 };

// The worker's program. Kept as a string and started with `eval` so that the
// runtime stays a single file: a separate worker script would have to be found
// on disk at run time, which a bundled build cannot rely on.
//Provides: fstar_worker_source
var fstar_worker_source = [
  'const { parentPort, workerData } = require("node:worker_threads");',
  'const cp = require("node:child_process");',
  'const L = workerData.layout;',
  'const ctl = new Int32Array(workerData.sab, 0, 16);',
  'const bytes = new Uint8Array(workerData.sab);',
  'const procs = new Map();',
  '',
  '// Publish a reply and wake the blocked thread. status: 0 ok, 1 error.',
  'function reply(status, buf) {',
  '  const b = buf || Buffer.alloc(0);',
  '  const n = Math.min(b.length, L.SIZE - L.DATA);',
  '  bytes.set(b.subarray(0, n), L.DATA);',
  '  Atomics.store(ctl, L.LENGTH, n);',
  '  Atomics.store(ctl, L.STATUS, status);',
  '  Atomics.store(ctl, L.READY, 1);',
  '  Atomics.notify(ctl, L.READY);',
  '}',
  '',
  '// A stream the parent reads from. Output is buffered as it arrives; a read',
  '// that finds nothing is parked until data or end-of-file arrives.',
  'function mkStream(s) {',
  '  const st = { chunks: [], len: 0, ended: false, waiter: null };',
  '  const end = () => { st.ended = true; serve(st); };',
  '  s.on("data", (d) => { st.chunks.push(d); st.len += d.length; serve(st); });',
  '  // close as well as end: a stream can be torn down without ending, and a',
  '  // read parked on it would otherwise never be answered.',
  '  s.on("end", end); s.on("close", end); s.on("error", end);',
  '  return st;',
  '}',
  'function take(st, max) {',
  '  const b = Buffer.concat(st.chunks, st.len);',
  '  const n = Math.min(max, b.length);',
  '  const head = b.subarray(0, n), rest = b.subarray(n);',
  '  st.chunks = rest.length ? [rest] : []; st.len = rest.length;',
  '  return head;',
  '}',
  '// A parked read completes as soon as there is anything to return, or with',
  '// zero bytes at end-of-file, which is how the reader learns the solver died.',
  'function serve(st) {',
  '  if (!st.waiter) return;',
  '  if (st.len > 0) { const w = st.waiter; st.waiter = null; reply(0, take(st, w)); }',
  '  else if (st.ended) { st.waiter = null; reply(0, Buffer.alloc(0)); }',
  '}',
  '',
  'parentPort.on("message", (m) => {',
  '  try {',
  '    if (m.op === "spawn") {',
  '      const child = cp.spawn(m.prog, m.args, { stdio: ["pipe", "pipe", "pipe"], env: m.env });',
  '      const e = { child: child, exited: false, code: 0 };',
  '      e.out = mkStream(child.stdout);',
  '      e.err = mkStream(child.stderr);',
  '      // A solver that has already exited leaves nothing to write to; a real',
  '      // pipe would report that on the read side, so drop the error here.',
  '      child.stdin.on("error", () => {});',
  '      child.on("exit", (code) => {',
  '        e.exited = true; e.code = code === null ? 0 : code;',
  '      });',
  '      child.on("error", (err) => {',
  '        e.exited = true; e.code = 127;',
  '        e.out.ended = true; e.err.ended = true; serve(e.out); serve(e.err);',
  '      });',
  '      procs.set(m.id, e);',
  '      reply(0, Buffer.from(String(child.pid || 0)));',
  '      return;',
  '    }',
  '    const e = procs.get(m.id);',
  '    if (!e) { reply(1, Buffer.from("ESRCH")); return; }',
  '    switch (m.op) {',
  '      case "write":',
  '        try { e.child.stdin.write(Buffer.from(m.data)); } catch (err) {}',
  '        reply(0, null); return;',
  '      case "closeStdin":',
  '        try { e.child.stdin.end(); } catch (err) {}',
  '        reply(0, null); return;',
  '      case "read": {',
  '        const st = m.which === 2 ? e.err : e.out;',
  '        const max = Math.min(m.max, L.SIZE - L.DATA);',
  '        if (st.len > 0) { reply(0, take(st, max)); return; }',
  '        if (st.ended) { reply(0, Buffer.alloc(0)); return; }',
  '        st.waiter = max; return;   // parked; serve() replies later',
  '      }',
  '      case "poll": {',
  '        const st = m.which === 2 ? e.err : e.out;',
  '        const max = Math.min(m.max, L.SIZE - L.DATA);',
  '        reply(0, st.len > 0 ? take(st, max) : Buffer.alloc(0)); return;',
  '      }',
  '      case "kill":',
  '        try { e.child.kill("SIGKILL"); } catch (err) {}',
  '        // Mark the streams done rather than waiting for their teardown, so a',
  '        // later read reports end-of-file instead of parking on a dead child.',
  '        e.out.ended = true; e.err.ended = true; serve(e.out); serve(e.err);',
  '        reply(0, null); return;',
  '      case "reap":',
  '        procs.delete(m.id);',
  '        reply(0, Buffer.from(e.exited ? String(e.code) : "running")); return;',
  '      default: reply(1, Buffer.from("EINVAL")); return;',
  '    }',
  '  } catch (err) { reply(1, Buffer.from(String(err && err.message))); }',
  '});',
  '',
  '// The caller is blocked in Atomics.wait, so it cannot notice that this',
  '// thread has died: anything fatal has to be reported through the buffer',
  '// before the thread goes, or the caller waits for a reply that cannot come.',
  'process.on("uncaughtException", (err) => {',
  '  try { reply(1, Buffer.from("worker: " + String(err && err.message))); } catch (e) {}',
  '  process.exit(1);',
  '});',
  '// Nothing kills a child when its parent goes, so do it here: this thread',
  '// ends when the process does, including when the process is signalled.',
  'process.on("exit", () => {',
  '  for (const e of procs.values()) { try { e.child.kill("SIGKILL"); } catch (err) {} }',
  '});'
].join("\n");

// The worker and the shared buffer, created when the first process is spawned.
//Provides: fstar_bridge
//Requires: fstar_bridge_layout, fstar_worker_source, caml_raise_sys_error
var fstar_bridge = {
  worker: null, ctl: null, bytes: null, next_id: 1, pids: {},
  get: function () {
    if (this.worker) return this;
    var L = fstar_bridge_layout;
    var wt;
    try { wt = require("node:worker_threads"); }
    catch (e) { caml_raise_sys_error("subprocesses need Node's worker_threads"); }
    if (typeof globalThis.SharedArrayBuffer !== "function")
      caml_raise_sys_error("subprocesses need globalThis.SharedArrayBuffer");
    var sab = new globalThis.SharedArrayBuffer(L.SIZE);
    this.ctl = new Int32Array(sab, 0, 16);
    this.bytes = new Uint8Array(sab);
    this.worker = new wt.Worker(fstar_worker_source,
                                { eval: true, workerData: { sab: sab, layout: L } });
    // Do not let a live worker keep the process alive once F* is done.
    this.worker.unref();
    // An unref'd worker is not torn down by a signal that ends the process, and
    // its children would outlive us. Terminating it runs its exit handler,
    // which kills them. Nothing can be done about SIGKILL.
    var self = this, p = globalThis.process;
    var stop = function () { try { self.worker.terminate(); } catch (e) {} };
    p.on("exit", stop);
    ["SIGINT", "SIGTERM", "SIGHUP"].forEach(function (sig) {
      p.on(sig, function handler() {
        stop();
        p.removeListener(sig, handler);
        p.kill(p.pid, sig);
      });
    });
    return this;
  },
  // Post a request and block until the worker answers. The reply is left in
  // shared memory rather than posted back, because a blocked thread cannot
  // receive messages.
  call: function (msg) {
    var L = fstar_bridge_layout, b = this.get();
    globalThis.Atomics.store(b.ctl, L.READY, 0);
    b.worker.postMessage(msg);
    globalThis.Atomics.wait(b.ctl, L.READY, 0);
    var n = globalThis.Atomics.load(b.ctl, L.LENGTH);
    var out = b.bytes.slice(L.DATA, L.DATA + n);
    if (globalThis.Atomics.load(b.ctl, L.STATUS) !== 0)
      caml_raise_sys_error("subprocess: " + String.fromCharCode.apply(null, out));
    return out;
  }
};

// A pipe end.
//
// Both ends of a pipe start out here, holding an in-memory queue: that is what
// FStarC.Util's signal pipe is, and it needs no child. When the pipe is handed
// to a child the ends part company -- the child's end is the real stream, and
// this side reads or writes it through the worker.
//
// Departs from POSIX in that a write to an in-memory pipe never blocks and the
// queue is unbounded, so a reader that never drains costs memory rather than
// stalling the writer. F*'s signal pipe carries one byte at a time.
//Provides: MlProcPipe
//Requires: fstar_bridge, fstar_run_deferred_thread
function MlProcPipe(readable) {
  this.readable = readable;   // which end of the pair this is
  this.queue = [];            // in-memory bytes, before any child is attached
  this.proc = null;           // set once this end belongs to a spawned child
  this.which = 0;             // 1 = child's stdout, 2 = child's stderr
  this.closed = false;
  this.is_proc_pipe = true;
  this.flags = { noSeek: true, buffered: 0, wronly: readable ? 0 : 1 };
}
MlProcPipe.prototype.pos = function () { return 0; };
// in_channel_of_descr and out_channel_of_descr refuse anything that is not
// stream-like, and a pipe is.
MlProcPipe.prototype.check_stream_semantics = function (cmd) { return 0; };
MlProcPipe.prototype.stat = function () { return { kind: 3, size: 0 }; };

MlProcPipe.prototype.read = function (a, off, len, raise_unix) {
  // FStarC.Util waits for its reader by blocking on a one-byte pipe that only
  // the reader writes. On a single thread that would deadlock, so a read that
  // is about to block is where the deferred reader runs: it fills this pipe,
  // and the read then finds its byte.
  if (!this.proc && !this.queue.length) fstar_run_deferred_thread();
  if (this.queue.length) {
    var n = Math.min(len, this.queue.length);
    for (var i = 0; i < n; i++) a[off + i] = this.queue[i];
    this.queue = this.queue.slice(n);
    return n;
  }
  if (!this.proc) return 0;   // in-memory pipe with nothing in it
  var got = fstar_bridge.call({ op: "read", id: this.proc, which: this.which, max: len });
  a.set(got, off);
  return got.length;
};

MlProcPipe.prototype.write = function (buf, off, len, raise_unix) {
  if (this.proc) {
    fstar_bridge.call({ op: "write", id: this.proc,
                        data: Array.prototype.slice.call(buf, off, off + len) });
    return len;
  }
  // A write goes to whoever reads the other end.
  var target = this.peer || this;
  for (var i = 0; i < len; i++) target.queue.push(buf[off + i]);
  return len;
};

MlProcPipe.prototype.close = function (raise_unix) {
  if (this.closed) return 0;
  this.closed = true;
  if (this.proc && this.which === 0) {
    try { fstar_bridge.call({ op: "closeStdin", id: this.proc }); } catch (e) {}
  }
  return 0;
};

//Provides: caml_unix_pipe
//Requires: MlProcPipe, caml_sys_fds
function caml_unix_pipe(cloexec, vunit) {
  var r = new MlProcPipe(true), w = new MlProcPipe(false);
  r.peer = w; w.peer = r;
  var rfd = caml_sys_fds.length; caml_sys_fds[rfd] = { file: r };
  var wfd = caml_sys_fds.length; caml_sys_fds[wfd] = { file: w };
  return [0, rfd, wfd];
}

// The child does not inherit descriptors -- caml_unix_spawn hands the worker a
// program to run, not a file table -- so close-on-exec has nothing to act on.
//Provides: caml_unix_set_close_on_exec
function caml_unix_set_close_on_exec(fd) { return 0; }
//Provides: caml_unix_clear_close_on_exec
function caml_unix_clear_close_on_exec(fd) { return 0; }

// Duplicates the descriptor, not the open file: both entries name the same
// pipe end, which is all the callers here need.
//Provides: caml_unix_dup
//Requires: caml_sys_fds, caml_unix_lookup_file
function caml_unix_dup(cloexec, fd) {
  var file = caml_unix_lookup_file(fd, "dup");
  var n = caml_sys_fds.length;
  caml_sys_fds[n] = { file: file };
  return n;
}

// Starts the child in the worker and attaches the three descriptors the caller
// passed to its streams. Those descriptors are the child's ends of pipes made
// by caml_unix_pipe; from here on this side reads and writes them through the
// worker rather than from its own queue.
//
// Departs from POSIX in two ways: the returned pid belongs to a process this
// thread does not own, so only kill and waitpid below understand it; and a
// program that cannot be run is reported later, as end-of-file on its output,
// rather than as an error from here.
//Provides: caml_unix_spawn
//Requires: fstar_bridge, caml_unix_lookup_file, caml_jsstring_of_string, caml_raise_system_error
function caml_unix_spawn(prog, args, optenv, usepath, redirections) {
  var id = fstar_bridge.next_id++;
  var argv = [];
  // args carries argv[0], which child_process.spawn supplies itself.
  for (var i = 2; i < args.length; i++) argv.push(caml_jsstring_of_string(args[i]));
  var env = undefined;
  if (optenv && optenv !== 0) {
    env = {};
    var a = optenv[1];
    for (var k = 1; k < a.length; k++) {
      var kv = caml_jsstring_of_string(a[k]), eq = kv.indexOf("=");
      if (eq > 0) env[kv.slice(0, eq)] = kv.slice(eq + 1);
    }
  }
  // redirections is an OCaml array of the child's three descriptors, tag first.
  // Those ends are the child's; this side talks to the child through their
  // peers, and closes its copy of the child's ends straight after spawning.
  // Checked before spawning, so a bad call cannot strand a running child.
  var ends = [];
  for (var j = 1; j <= 3; j++) {
    var f = caml_unix_lookup_file(redirections[j], "spawn");
    if (!f.is_proc_pipe || !f.peer) caml_raise_system_error(1, "EINVAL", "spawn");
    ends.push(f.peer);
  }
  var pid = fstar_bridge.call({ op: "spawn", id: id, env: env,
                                prog: caml_jsstring_of_string(prog), args: argv });
  for (var k = 0; k < 3; k++) { ends[k].proc = id; ends[k].which = k; }
  var pid_s = String.fromCharCode.apply(null, pid);
  fstar_bridge.pids[pid_s] = id;
  return parseInt(pid_s, 10) || 0;
}

//Provides: fstar_proc_id_of_pid
//Requires: fstar_bridge
function fstar_proc_id_of_pid(pid) {
  var m = fstar_bridge.pids || {};
  return m[String(pid)];
}

// Reports an exit the worker has already seen, as a normal exit whatever ended
// the child. It does not wait: F* asks only after killing the child, and a
// thread blocked here is the one that would have to observe the exit.
//Provides: caml_unix_waitpid
//Requires: fstar_bridge, fstar_proc_id_of_pid
function caml_unix_waitpid(flags, pid) {
  var id = fstar_proc_id_of_pid(pid);
  if (id === undefined) return [0, pid, [0, 0]];
  var s = "";
  try { s = String.fromCharCode.apply(null, fstar_bridge.call({ op: "reap", id: id })); }
  catch (e) { return [0, pid, [0, 0]]; }
  delete fstar_bridge.pids[String(pid)];
  if (s === "running") return [0, pid, [0, 0]];
  return [0, pid, [0, parseInt(s, 10) || 0]];   // WEXITED
}

//Provides: caml_unix_kill
//Requires: fstar_bridge, fstar_proc_id_of_pid, caml_raise_system_error
function caml_unix_kill(pid, signum) {
  var id = fstar_proc_id_of_pid(pid);
  if (id === undefined) caml_raise_system_error(1, "ESRCH", "kill");
  fstar_bridge.call({ op: "kill", id: id });
  return 0;
}

// Only the zero-timeout poll of a single read descriptor is supported, which is
// how FStarC.Util drains the solver's stderr without blocking. Any use of the
// write or except sets, or a non-zero timeout, is refused rather than answered
// wrongly.
//
// The poll takes whatever the worker has buffered and keeps it on the
// descriptor for the following read, since there is no way to ask a stream how
// much it holds without taking it.
//Provides: caml_unix_select
//Requires: caml_unix_lookup_file, fstar_bridge, caml_raise_system_error
function caml_unix_select(rfds, wfds, efds, timeout) {
  if (wfds !== 0 || efds !== 0 || timeout > 0)
    caml_raise_system_error(1, "EINVAL", "select");
  var ready = 0;
  if (rfds !== 0) {
    var fd = rfds[1];
    var file = caml_unix_lookup_file(fd, "select");
    if (file.is_proc_pipe) {
      if (!file.queue.length && file.proc) {
        // Take no more than FStarC.Util's non-blocking drain will consume
        // before it polls again, rather than hoarding the solver's output here.
        var got = fstar_bridge.call({ op: "poll", id: file.proc, which: file.which, max: 1024 });
        for (var i = 0; i < got.length; i++) file.queue.push(got[i]);
      }
      if (file.queue.length) ready = [0, fd, 0];
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
// This is not a threading implementation. It holds one closure at a time and
// rejects a second rather than losing it, and it runs that closure at a point
// the caller chose for another reason; anything that needs two runnable threads
// will not work.
//Provides: fstar_deferred_thread
var fstar_deferred_thread = { pending: null, next_id: 1 };

//Provides: caml_thread_new
//Requires: fstar_deferred_thread, caml_failwith
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
