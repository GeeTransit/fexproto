#
# Copyright (C) 2024-2026 George Zhang
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

# Optional RPython imports
try:
    from rpython.rlib.rsre import rsre_re as re
    from rpython.rlib import rweakref
    from rpython.rlib import jit
    from rpython.rlib import objectmodel
    from rpython.rlib import rfile
except ImportError:
    import re
    class rweakref(object):
        class RWeakKeyDictionary(object):
            def __init__(self, *args):
                import weakref
                self._data = weakref.WeakKeyDictionary()
            def get(self, key): return self._data.get(key, None)
            def set(self, key, value): self._data[key] = value
    class jit(object):
        class JitDriver(object):
            def __init__(self, **kwargs): pass
            def jit_merge_point(self, **kwargs): pass
            def can_enter_jit(self, **kwargs): pass
        @staticmethod
        def set_param(*args): pass
        @staticmethod
        def set_user_param(*args): pass
        @staticmethod
        def promote(arg): return arg
        @staticmethod
        def promote_string(arg): return arg
        @staticmethod
        def elidable(func): return func
        @staticmethod
        def unroll_safe(func): return func
        @staticmethod
        def isvirtual(arg): return False
        @staticmethod
        def isconstant(arg): return False
        @staticmethod
        def we_are_jitted(): return False
    class objectmodel(object):
        class specialize(object):
            @staticmethod
            def call_location(): return lambda func: func
    class rfile(object):
        @staticmethod
        def create_file(filename):
            return open(filename, "rb")
        if b"" == "":  # Python 2
            @staticmethod
            def create_stdio():
                import sys, os
                # TODO: is this the correct way to reopen files in binary mode?
                return (
                    os.fdopen(sys.stdin.fileno(), "rb", 0),
                    os.fdopen(sys.stdout.fileno(), "wb", 0),
                    os.fdopen(sys.stderr.fileno(), "wb", 0),
                )
        else:
            @staticmethod
            def create_stdio():
                import sys
                return sys.stdin.buffer, sys.stdout.buffer, sys.stderr.buffer

# == Interpreter types and logic

class Object(object):
    _attrs_ = _immutable_fields_ = ()
class Nil(Object):
    _attrs_ = _immutable_fields_ = ()
class Ignore(Object):
    _attrs_ = _immutable_fields_ = ()
class Inert(Object):
    _attrs_ = _immutable_fields_ = ()
class Boolean(Object):
    _attrs_ = _immutable_fields_ = ("value",)
    def __init__(self, value):
        assert isinstance(value, bool)
        self.value = value
class Pair(Object):
    _attrs_ = _immutable_fields_ = ("car", "cdr")
    def __init__(self, car, cdr):
        assert isinstance(car, Object)
        assert isinstance(cdr, Object)
        self.car = car
        self.cdr = cdr
ImmutablePair = Pair
class MutablePair(Pair):
    _attrs_ = ("car", "cdr")
    _immutable_fields_ = ()
class Int(Object):
    _attrs_ = _immutable_fields_ = ("value",)
    def __init__(self, value):
        assert isinstance(value, int)
        self.value = value
class String(Object):
    _attrs_ = _immutable_fields_ = ("value",)
    def __init__(self, value):
        assert isinstance(value, bytes)
        self.value = value
class Symbol(Object):
    _attrs_ = _immutable_fields_ = ("name",)
    def __init__(self, name):
        assert isinstance(name, bytes)
        self.name = name
class Environment(Object):
    _immutable_fields_ = ("storage", "parent")
    def __init__(self, bindings, parent):
        assert parent is None or isinstance(parent, Environment)
        storage, localmap = _environment_tostoragemap(bindings)
        self.storage = storage
        self.parent = parent
        self.localmap = localmap
class Continuation(Object):
    _immutable_fields_ = ("env", "operative", "parent")
    _attrs_ = _immutable_fields_ + ("_should_enter", "_call_info")
    def __init__(self, env, operative, parent):
        assert env is None or isinstance(env, Environment)
        assert isinstance(operative, Operative)
        assert parent is None or isinstance(parent, Continuation)
        self.env = env
        self.operative = operative
        self.parent = parent
        self._should_enter = False
        self._call_info = None
class Combiner(Object):
    _immutable_fields_ = ("num_wraps", "operative")
    def __init__(self, num_wraps, operative):
        self.num_wraps = num_wraps
        self.operative = operative
NIL = Nil()
IGNORE = Ignore()
INERT = Inert()
TRUE = Boolean(True)
FALSE = Boolean(False)

class Operative(object):
    _immutable_ = True
    def call(self, env, value, parent): assert False
class PrimitiveOperative(Operative):
    _immutable_ = True
    def __init__(self, func):
        self.func = func
    def call(self, env, value, parent):
        try:
            return self.func(env, value, parent)
        except RuntimeError as e:
            return f_error(parent, MutablePair(String(_c_str_to_bytes(e.message)), NIL))
class ContinuationOperative(Operative):
    _immutable_ = True
    def __init__(self, continuation):
        self.continuation = continuation
    def call(self, env, value, parent):
        # TODO: replace with abnormal pass when guarded continuations implemented
        return f_return(self.continuation, value)
class UserDefinedOperative(Operative):
    _immutable_ = True
    def __init__(self, env, envname, name, body):
        assert env is None or isinstance(env, Environment)
        self.env = env
        assert isinstance(envname, Symbol) or isinstance(envname, Ignore)
        self.envname = envname
        assert not isinstance(name, MutablePair)
        self.name = name
        assert not isinstance(body, MutablePair)
        self.body = body
    def call(self, env, value, parent):
        call_env = Environment({}, self.env)
        envname = self.envname
        if isinstance(envname, Symbol):
            _environment_update(call_env, envname, env)
        name = self.name
        try:
            _define(call_env, name, value)
        except RuntimeError as e:
            return f_error(parent, MutablePair(String(_c_str_to_bytes(e.message)), NIL))
        return f_eval(call_env, self.body, parent)

def _f_noop(env, expr, parent):
    return f_return(parent, expr)
NOOP = PrimitiveOperative(_f_noop)

# Interpreter-wide mapping from pair to location info
class Location(object):
    def __init__(self, filename, start_line_no, start_char_no, end_line_no, end_char_no):
        assert isinstance(filename, bytes)
        self.filename = filename
        assert isinstance(start_line_no, int)
        self.start_line_no = start_line_no
        assert isinstance(start_char_no, int)
        self.start_char_no = start_char_no
        assert isinstance(end_line_no, int)
        self.end_line_no = end_line_no
        assert isinstance(end_char_no, int)
        self.end_char_no = end_char_no
LOCATIONS = rweakref.RWeakKeyDictionary(Object, Location)

def _copy_immutable_recursively_set(expr, visited):
    if not isinstance(expr, MutablePair):
        return expr
    if expr in visited:
        return visited[expr]
    pair = ImmutablePair(NIL, NIL)
    visited[expr] = pair
    pair.car = _copy_immutable_recursively_set(expr.car, visited)
    pair.cdr = _copy_immutable_recursively_set(expr.cdr, visited)
    return pair
@jit.unroll_safe
def _copy_immutable_recursively_list(expr, visited):
    if not isinstance(expr, MutablePair):
        return expr
    for before, after in visited:
        if expr is before:
            return after
    pair = ImmutablePair(NIL, NIL)
    visited.append((expr, pair))
    pair.car = _copy_immutable_recursively_list(expr.car, visited)
    pair.cdr = _copy_immutable_recursively_list(expr.cdr, visited)
    return pair
def _f_copy_immutable(expr):
    if not jit.we_are_jitted():
        return _copy_immutable_recursively_set(expr, {})
    else:
        return _copy_immutable_recursively_list(expr, [])

# Exceptions

class ParsingError(Exception):
    def __init__(self, message, line_no, char_no):
        self.message = message
        # Note that line_no and char_no must be on the exception instance since
        # unlike internal errors, there is no "source expression" to locate.
        self.line_no = line_no
        self.char_no = char_no
OldRuntimeError = RuntimeError
class RuntimeError(OldRuntimeError):
    def __init__(self, message):
        # RPython exception instances don't have .message
        self.message = message
class EvaluationError(Exception):
    def __init__(self, value, parent=None):
        # Actual exception which stops the evaluation loop
        self.value = value
        self.parent = parent
class EvaluationDone(Exception):
    def __init__(self, value):
        # Resolved value which stops the evaluation loop
        self.value = value

def _f_error_cont(env, expr, parent):
    if isinstance(expr, Pair):
        original_parent = expr.car
        if isinstance(original_parent, Continuation):
            raise EvaluationError(expr.cdr, original_parent)
    raise EvaluationError(expr)
ERROR_CONT = Continuation(None, PrimitiveOperative(_f_error_cont), None)
def _f_evaluation_done(env, expr, parent):
    raise EvaluationDone(expr)
EVALUATION_DONE = PrimitiveOperative(_f_evaluation_done)

# Variable lookup and environment versioning

# We assume that most environments assign the same variables in the same order.
# This lets us optimize local variable lookups to be just an array access. See
# https://pypy.org/posts/2011/03/controlling-tracing-of-interpreter-with_21-6524148550848694588.html

# Also note that we are using symbols themselves as keys, not the name. The
# idea is that different functions which happen to share the same variable
# names shouldn't be handled the same.

# These are placeholder values for a binding's known value.
_INITIAL = Object()  # Just initialized
_MUTATED = Object()  # Symbol gets assigned different values

class LocalMap(object):
    _immutable_fields_ = ("transitions", "symbol", "index", "parent", "known_value?", "cached_attrs")
    def __init__(self, symbol, index, parent):
        self.transitions = {}  # Symbol -> LocalMap
        assert symbol is None or isinstance(symbol, Symbol)
        self.symbol = symbol
        assert isinstance(index, int)
        self.index = index
        assert parent is None or isinstance(parent, LocalMap)
        self.parent = parent
        self.known_value = _INITIAL
        self.cached_attrs = {}
    @jit.elidable
    def find(self, name):
        assert isinstance(name, bytes)
        if name in self.cached_attrs:
            return self.cached_attrs[name]
        attr = self._find(name)
        self.cached_attrs[name] = attr
        return attr
    def _find(self, name):
        if self.symbol is None:
            return None
        if self.symbol.name == name:
            return self
        return self.parent._find(name)
    @jit.elidable
    def new_localmap_with(self, name):
        assert isinstance(name, Symbol)
        if name not in self.transitions:
            new = LocalMap(name, self.index + 1, self)
            self.transitions[name] = new
        return self.transitions[name]
_ROOT_LOCALMAP = LocalMap(None, -1, None)

@jit.unroll_safe
def _environment_tostoragemap(bindings):
    storage = []
    localmap = _ROOT_LOCALMAP
    if bindings is not None and len(bindings) > 0:
        for key, value in bindings.items():  # TODO: should we sort?
            # TODO: How to ensure same logic as in _environment_update?
            localmap = localmap.new_localmap_with(Symbol(key))
            if localmap.known_value is _INITIAL:
                localmap.known_value = value
            elif localmap.known_value is _MUTATED:
                pass
            elif localmap.known_value is not value:
                localmap.known_value = _MUTATED
            storage.append(value)
    return storage, localmap

@jit.unroll_safe
def _environment_lookup(env, name):
    if not jit.isvirtual(name):
        jit.promote(name)
    name_name = name.name
    if not jit.isvirtual(name_name):
        jit.promote_string(name_name)
    while env is not None:
        # Promote the local map since the combiner calls should be the same,
        # hence variable lookups should be on the same lexical environments.
        jit.promote(env.localmap)
        attr = env.localmap.find(name_name)
        if attr is not None:
            # If the binding is a constant, return the known value
            if attr.known_value is not _INITIAL and attr.known_value is not _MUTATED:
                return attr.known_value
            return env.storage[attr.index]
        env = env.parent
    return None

def _environment_update(env, name, value):
    if not jit.isvirtual(name):
        jit.promote(name)
    name_name = name.name
    if not jit.isvirtual(name_name):
        jit.promote_string(name_name)
    attr = env.localmap.find(name_name)
    if attr is not None:
        # Invalidate traces if the binding differs from the previous constant
        if attr.known_value is not _MUTATED and attr.known_value is not value:
            attr.known_value = _MUTATED
        env.storage[attr.index] = value
    else:
        attr = env.localmap = env.localmap.new_localmap_with(name)
        # Initialize binding's known value, otherwise invalidate if different
        if attr.known_value is _INITIAL:
            attr.known_value = value
        elif attr.known_value is _MUTATED:
            pass
        elif attr.known_value is not value:
            attr.known_value = _MUTATED
        env.storage.append(value)

# Specialized environments

class StepWrappedEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("env", "args")
    def __init__(self, env, args):
        Environment.__init__(self, None, None)
        self.env = env
        self.args = args
class StepEvCarEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("env", "operative", "num_wraps", "todo", "p", "c", "i", "res")
    def __init__(self, env, operative, num_wraps, todo, p, c, i, res):
        Environment.__init__(self, None, None)
        self.env = env
        self.operative = operative
        self.num_wraps = num_wraps
        self.todo = todo
        self.p = p
        self.c = c
        self.i = i
        self.res = res
class FRemoteEvalEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("expression",)
    def __init__(self, expression):
        Environment.__init__(self, None, None)
        self.expression = expression
class FIfEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("env", "then", "orelse")
    def __init__(self, env, then, orelse):
        Environment.__init__(self, None, None)
        self.env = env
        self.then = then
        self.orelse = orelse
class FDefineEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("env", "name")
    def __init__(self, env, name):
        Environment.__init__(self, None, None)
        self.env = env
        self.name = name
class FBindsEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("name",)
    def __init__(self, name):
        Environment.__init__(self, None, None)
        self.name = name

# Core interpreter logic

def _f_toplevel_eval(env, expr):
    parent = Continuation(None, EVALUATION_DONE, None)
    parent._call_info = expr
    return f_eval(env, expr, parent)

def f_return(parent, obj):
    return None, obj, parent
def f_return_loop_constant(parent, obj):
    return obj, None, parent
def f_error(parent, value):
    # TODO: replace with abnormal pass when guarded continuations implemented
    return f_return(ERROR_CONT, MutablePair(parent, value))
def f_eval(env, obj, parent=None):
    # Don't let the JIT driver promote virtuals (such as mutable pairs
    # constructed at runtime)
    if not jit.isconstant(obj):
        next_continuation = Continuation(env, _STEP_EVAL, parent)
        return f_return(next_continuation, obj)
    return obj, env, parent

def _step_eval(env, obj, parent):
    return step_evaluate((obj, env, parent))
_STEP_EVAL = PrimitiveOperative(_step_eval)

def step_evaluate(state):
    obj, env, parent = state
    # Return values should usually not be promoted (red variables) unless they
    # are loop constants (green variables).
    if obj is None:  # normal return
        assert env is not None
        return parent.operative.call(parent.env, env, parent.parent)
    if env is None:  # loop constant
        assert obj is not None
        return parent.operative.call(parent.env, obj, parent.parent)
    if isinstance(obj, Symbol):
        assert isinstance(env, Environment)
        value = _environment_lookup(env, obj)
        if value is None:
            return f_error(parent, MutablePair(String(b"binding not found"), MutablePair(obj, NIL)))
        return f_return(parent, value)
    elif isinstance(obj, Pair):
        next_env = StepWrappedEnvironment(env, obj.cdr)
        next_continuation = Continuation(next_env, _STEP_CALL_WRAPPED, parent)
        next_continuation._call_info = obj.car
        return f_eval(env, obj.car, next_continuation)
    else:
        return f_return(parent, obj)

jitdriver = jit.JitDriver(
    greens=["expr"],
    reds=["env", "continuation"],
    is_recursive=True,
)

def fully_evaluate(state):
    expr, env, continuation = state
    try:
        while True:
            jitdriver.jit_merge_point(expr=expr, env=env, continuation=continuation)
            expr, env, continuation = step_evaluate((expr, env, continuation))
            if continuation._should_enter:
                jitdriver.can_enter_jit(expr=expr, env=env, continuation=continuation)
    except EvaluationDone as e:
        return e.value

# TODO: Look into how Pycket does runtime call-graph construction to
# automatically infer loops. See https://doi.org/10.1145/2858949.2784740
def _f_loop_constant(env, expr, parent):
    return f_return(parent, INERT)
def _f_loop_head(env, expr, parent):
    next_continuation = Continuation(None, _F_LOOP_CONSTANT, parent)
    next_continuation._should_enter = True
    return f_return_loop_constant(next_continuation, expr)
_F_LOOP_CONSTANT = PrimitiveOperative(_f_loop_constant)
_F_LOOP_HEAD = PrimitiveOperative(_f_loop_head)

@jit.unroll_safe
def _step_call_wrapped(static, combiner, parent):
    assert isinstance(static, StepWrappedEnvironment)
    env = static.env
    args = static.args
    if not isinstance(combiner, Combiner):
        raise RuntimeError("combiner call car must be combiner")
    # Promoting combiners should work in loops since otherwise the loop logic
    # would be different each iteration.
    if not jit.isvirtual(combiner):
        jit.promote(combiner)
    jit.promote(combiner.num_wraps)
    if not jit.isvirtual(combiner.operative):
        jit.promote(combiner.operative)
    if combiner.num_wraps == 0 or isinstance(args, Nil):
        return f_return(Continuation(env, combiner.operative, parent), args)
    # Brent's cycle finding algorithm
    x = y = args
    step = 1
    c = a = 0
    while isinstance(x, Pair):
        x = x.cdr
        c += 1
        if x == y:  # cycle of length c found
            x = y = args
            for _ in range(c):
                assert isinstance(x, Pair)
                x = x.cdr
            a = 0
            while x != y:
                assert isinstance(x, Pair)
                assert isinstance(y, Pair)
                x = x.cdr
                y = y.cdr
                a += 1
            p = a + c
            n = 0
            break
        if c == step:
            step *= 2
            y = x
            a += c
            c = 0
    else:  # acyclic args
        a += c
        p = a
        c = 0
        n = 1 if isinstance(x, Nil) else 0
    if c == 0 and n == 0:
        raise RuntimeError("applicative call args must be proper list")
    assert isinstance(args, Pair)
    next_expr = args.car
    next_env = StepEvCarEnvironment(env, combiner.operative, combiner.num_wraps, args.cdr, p, c, 0, NIL)
    next_continuation = Continuation(next_env, _STEP_CALL_EVCAR, parent)
    next_continuation._call_info = next_expr
    return f_eval(env, next_expr, next_continuation)
_STEP_CALL_WRAPPED = PrimitiveOperative(_step_call_wrapped)

@jit.unroll_safe
def _step_call_evcar(static, value, parent):
    assert isinstance(static, StepEvCarEnvironment)
    env = static.env
    assert isinstance(env, Environment)
    operative = static.operative
    assert isinstance(operative, Operative)
    num_wraps = static.num_wraps
    assert isinstance(num_wraps, int)
    todo = static.todo
    assert isinstance(todo, Nil) or isinstance(todo, Pair)
    p = static.p
    assert isinstance(p, int)
    c = static.c
    assert isinstance(c, int)
    i = static.i
    assert isinstance(i, int)
    res = static.res
    assert isinstance(res, Nil) or isinstance(res, Pair)
    res = MutablePair(value, res)
    i = i + 1
    if i == p:
        i = 0
        num_wraps = num_wraps - 1
        if c == 0:
            assert isinstance(todo, Nil)
        else:
            up = todo = MutablePair(NIL, NIL)
            for _ in range(c-1): assert isinstance(res, Pair); todo = MutablePair(res.car, todo); res = res.cdr
            assert isinstance(res, Pair)
            up.car = res.car
            up.cdr = todo
            res = res.cdr
            todo = up
            p -= c
        for _ in range(p): assert isinstance(res, Pair); todo = MutablePair(res.car, todo); res = res.cdr
        assert isinstance(todo, Pair)
        if num_wraps == 0:
            continuation = Continuation(env, operative, parent)
            return f_return(continuation, todo)
    assert isinstance(todo, Pair)
    next_env = StepEvCarEnvironment(env, operative, num_wraps, todo.cdr, p, c, i, res)
    next_expr = todo.car
    next_continuation = Continuation(next_env, _STEP_CALL_EVCAR, parent)
    next_continuation._call_info = next_expr
    return f_eval(env, next_expr, next_continuation)
_STEP_CALL_EVCAR = PrimitiveOperative(_step_call_evcar)

# == Lexing, parsing, and writing logic

if b"" == "":  # Python 2
    def _c_char_to_len1(char): return char
    def _c_len1_to_char(len1): return len1
    def _c_char_to_int(char): return ord(char)
    def _c_int_to_char(code): return chr(code)
    def _c_join_chars(chars): return b"".join(chars)
else:  # Python 3+
    def _c_char_to_len1(char): return chr(char)
    def _c_len1_to_char(len1): return ord(len1)
    def _c_char_to_int(char): return char
    def _c_int_to_char(code): return code
    def _c_join_chars(chars): return bytes(chars)
def _c_str_to_bytes(string): return _c_join_chars([_c_len1_to_char(len1) for len1 in string])
def _c_bytes_to_str(bytes_): return "".join([_c_char_to_len1(char) for char in bytes_])

_TOKEN_PATTERN = re.compile(b"|".join([
    br'[()]',  # open and close brackets
    br'[^ \t\r\n();"]+',  # symbol-like tokens
    br'"(?:[^"\\\r\n]|\\[^\r\n])*"',  # single-line strings
    br'[ \t\r]+',  # horizontal whitespace
    br'\n',  # newline (parsed separately to count lines)
    br';[^\r\n]*',  # single-line comments
]))
def tokenize(text, offsets=None, init_line_no=0, init_char_no=0):
    result = []
    i = 0
    len_text = len(text)
    line_no = init_line_no
    line_start_i = -init_char_no
    while i < len_text:
        match = _TOKEN_PATTERN.match(text, i)
        if match is None:
            raise ParsingError("unknown syntax", line_no, i - line_start_i)
        token = match.group()
        if token == b"\n":
            line_no += 1
            line_start_i = i + 1
        elif token[0] not in b" \t\r;":
            result.append(token)
            if offsets is not None:
                offsets.append(line_no)
                offsets.append(i - line_start_i)
        i = match.end()
    return result

_STRING_PATTERN = re.compile(b"|".join([
    br'[^\\]',  # normal characters
    br'\\x[a-fA-F0-9][a-fA-F0-9]',  # hex escape sequence
    br'\\[abtnr"\\]',  # common escape sequences
]))
def parse(tokens, offsets=None, locations=None, depth=0, upcons=None):
    token = tokens.pop()
    assert isinstance(token, bytes)
    line_no = offsets.pop() if offsets is not None else -1
    char_no = offsets.pop() if offsets is not None else -1
    if token == b")":
        raise ParsingError("unmatched close bracket", line_no, char_no)
    if token == b"(":
        expr, _, _ = _parse_elements(
            tokens,
            offsets=offsets, locations=locations,
            depth=depth, upcons=upcons,
            line_no=line_no, char_no=char_no,
            first_line_no=line_no, first_char_no=char_no,
        )
        return expr
    if token == b".":
        raise ParsingError("unexpected dot", line_no, char_no)
    if token == b"#t" or token == b"#T":
        return TRUE
    if token == b"#f" or token == b"#F":
        return FALSE
    if token.lower() == b"#ignore":
        return IGNORE
    if token.lower() == b"#inert":
        return INERT
    if upcons is not None and token.lower()[:4] == b"#up<" and token[-1] == b">"[0]:
        try:
            j = len(token)-1
            assert j >= 4
            up = int(token[4:j])
            if not 1 <= up <= depth:
                raise ValueError
        except ValueError:
            raise ParsingError("invalid up-reference amount", line_no, char_no)
        for i in range(depth-1, -1, -1):
            if i in upcons:
                break
            upcons[i] = MutablePair(NIL, NIL)
        return upcons[depth-up]
    if token[0] == b'"'[0]:
        i = 1
        len_token = len(token) - 1
        chars = []
        while i < len_token:
            match = _STRING_PATTERN.match(token, i)
            if match is None:
                raise ParsingError("unknown string escape", line_no, char_no + i)
            part = match.group()
            if part[0] != b"\\"[0]:
                chars.append(part[0])
            elif part[1] == b"x"[0]:
                chars.append(_c_int_to_char(int(part[2:4], 16)))
            else:
                chars.append(b'\a\b\t\n\r"\\'[b'abtnr"\\'.find(part[1])])
            i = match.end()
        return String(_c_join_chars(chars))
    if _c_char_to_len1(token[0]).isdigit() or token[0] in b"+-" and len(token) > 1 and _c_char_to_len1(token[1]).isdigit():
        try:
            return Int(int(token))
        except ValueError:
            raise ParsingError("unknown number", line_no, char_no)
    if token[0] != b"#"[0]:
        symbol = Symbol(token.lower())
        if locations is not None:
            locations.append((symbol, line_no, char_no, line_no, char_no + len(token)))
        return symbol
    raise ParsingError("unknown token", line_no, char_no)

def _parse_elements(
    tokens,
    offsets=None, locations=None,
    depth=0, upcons=None,
    line_no=-1, char_no=-1,
    first_line_no=-1, first_char_no=-1,
):
    if not tokens:
        raise ParsingError("unmatched open bracket", first_line_no, first_char_no)
    token = tokens[-1]
    if token == b")":
        tokens.pop()
        end_line_no = offsets.pop() if offsets is not None else -1
        end_char_no = offsets.pop() if offsets is not None else -1
        return NIL, end_line_no, end_char_no
    if token == b".":
        if line_no == first_line_no and char_no == first_char_no:
            line_no = offsets[-1] if offsets is not None else -1
            char_no = offsets[-2] if offsets is not None else -1
            raise ParsingError("missing car element", line_no, char_no)
        tokens.pop()
        if offsets is not None:
            offsets.pop()
            offsets.pop()
        if not tokens:
            raise ParsingError("unmatched open bracket and missing cdr element", first_line_no, first_char_no)
        if tokens[-1] == b")":
            line_no = offsets[-1] if offsets is not None else -1
            char_no = offsets[-2] if offsets is not None else -1
            raise ParsingError("unexpected close bracket", line_no, char_no)
        element = parse(tokens, offsets=offsets, locations=locations, depth=depth, upcons=upcons)
        if not tokens:
            raise ParsingError("unmatched open bracket", first_line_no, first_char_no)
        end_line_no = offsets.pop() if offsets is not None else -1
        end_char_no = offsets.pop() if offsets is not None else -1
        if tokens.pop() != b")":
            raise ParsingError("expected close bracket", end_line_no, end_char_no)
        return element, end_line_no, end_char_no
    element = parse(tokens, offsets=offsets, locations=locations, depth=depth+1, upcons=upcons)
    if not tokens:
        raise ParsingError("unmatched open bracket", first_line_no, first_char_no)
    next_line_no = offsets[-1] if offsets is not None else -1
    next_char_no = offsets[-2] if offsets is not None else -1
    rest, end_line_no, end_char_no = _parse_elements(
        tokens,
        offsets=offsets, locations=locations,
        depth=depth+1, upcons=upcons,
        line_no=next_line_no, char_no=next_char_no,
        first_line_no=first_line_no, first_char_no=first_char_no,
    )
    if depth not in upcons:
        pair = MutablePair(element, rest)
    else:
        pair = upcons.pop(depth)
        pair.car = element
        pair.cdr = rest
    if locations is not None:
        locations.append((pair, line_no, char_no, end_line_no, end_char_no + 1))
    return pair, end_line_no, end_char_no

# Helper class to handle REPL input state
class _InteractiveParser:
    def __init__(self):
        self.curr_lines = []
        self.curr_tokens = []
        self.curr_offsets = []
        self.curr_exprs = []
        self.curr_locations = []
        self.last_lines = None
    @staticmethod
    @objectmodel.specialize.call_location()
    def extendleft(a, b):
        a.reverse()
        a.extend(b)
        a.reverse()
    def handle(self, line, lines=None, locations=None):  # returns done, exprs
        if lines is None: lines = []
        if locations is None: locations = []
        # Add line to history
        if line and line[-1] == b"\n"[0]:
            self.curr_lines.append(line[:-1])
        else:
            self.curr_lines.append(line)
        try:
            # Try to tokenize the line
            temp_offsets = []
            temp_tokens = tokenize(
                line, offsets=temp_offsets,
                init_line_no=len(lines)+len(self.curr_lines)-1,
                init_char_no=0,
            )
            self.extendleft(self.curr_tokens, temp_tokens)
            self.extendleft(self.curr_offsets, temp_offsets)
            # Try to parse the tokens
            copy_tokens = self.curr_tokens[:]
            copy_offsets = self.curr_offsets[:]
            while copy_tokens:
                assert copy_offsets
                temp_locations = []
                temp_expr = parse(
                    copy_tokens,
                    offsets=copy_offsets,
                    locations=temp_locations,
                    upcons={},
                )
                self.curr_exprs.append(temp_expr)
                self.curr_locations.extend(temp_locations)
                del self.curr_tokens[len(copy_tokens):]
                del self.curr_offsets[len(copy_offsets):]
        except ParsingError as e:
            if e.message.startswith("unmatched open bracket"):
                # More input is needed
                return False, []
            # Save lines (for later printing) and clear state
            self.last_lines = self.curr_lines[:]
            del self.curr_lines[:]
            del self.curr_tokens[:]
            del self.curr_offsets[:]
            del self.curr_exprs[:]
            del self.curr_locations[:]
            raise
        # All tokens were parsed, return expressions
        lines.extend(self.curr_lines)
        locations.extend(self.curr_locations)
        copy_exprs = self.curr_exprs[:]
        del self.curr_lines[:]
        del self.curr_locations[:]
        del self.curr_exprs[:]
        return True, copy_exprs

def _prompt_lines(stdin, stdout, prompt_list):
    leftover = []
    while True:
        # Output the prompt if at the start of a line
        if not leftover:
            stdout.write(prompt_list[0])
            stdout.flush()
        # Read a chunk of data, usually ends with a newline
        part = stdin.readline()
        if not part:
            if leftover:
                yield "".join(leftover)
            return
        # Split on newlines and yield each line
        i = part.find(b"\n")
        if i < 0:
            leftover.append(part)
        else:
            leftover.append(part[:i+1])
            yield b"".join(leftover)
            del leftover[:]
            while True:
                j = part.find(b"\n", i+1)
                if j < 0:
                    if i+1 < len(part):
                        leftover.append(part[i+1:])
                    break
                else:
                    yield part[i+1:j+1]
                    i = j

def _f_write(file, obj):
    _write(file, obj, 0, {})
def _write(file, obj, depth, upcons):
    if isinstance(obj, Nil):
        file.write(b"()")
    elif isinstance(obj, Int):
        file.write(b"%d" % (obj.value,))
    elif isinstance(obj, String):
        file.write(b'"')
        for char in obj.value:
            code = _c_char_to_int(char)
            if char in b'\a\b\t\n\r"\\':  # escape sequences
                file.write(b"\\")
                file.write(_c_join_chars([b'abtnr"\\'[b'\a\b\t\n\r"\\'.find(char)]]))
            elif not 32 <= code < 128:  # unprintable codes
                file.write(b"\\x")
                file.write(_c_join_chars([b"0123456789abcdef"[code//16]]))
                file.write(_c_join_chars([b"0123456789abcdef"[code%16]]))
            else:
                file.write(_c_join_chars([char]))
        file.write(b'"')
    elif isinstance(obj, Symbol):
        file.write(obj.name)
    elif isinstance(obj, Ignore):
        file.write(b"#ignore")
    elif isinstance(obj, Inert):
        file.write(b"#inert")
    elif isinstance(obj, Boolean):
        if obj.value:
            file.write(b"#t")
        else:
            file.write(b"#f")
    elif isinstance(obj, Pair):
        if obj in upcons:
            file.write(b"#up<")
            file.write(b"%d" % (depth - upcons[obj],))
            file.write(b">")
            return
        stack = []
        file.write(b"(")
        stack.append(obj)
        upcons[obj] = depth
        depth += 1
        _write(file, obj.car, depth, upcons)
        obj_cdr = obj.cdr
        while isinstance(obj_cdr, Pair):
            if obj_cdr in upcons:
                break
            obj = obj_cdr
            file.write(b" ")
            stack.append(obj)
            upcons[obj] = depth
            depth += 1
            _write(file, obj.car, depth, upcons)
            obj_cdr = obj.cdr
        if not isinstance(obj_cdr, Nil):
            file.write(b" . ")
            _write(file, obj_cdr, depth, upcons)
        while stack:
            upcons.pop(stack.pop())
        file.write(b")")
    elif isinstance(obj, Environment):
        file.write(b"#environment")
    elif isinstance(obj, Continuation):
        file.write(b"#continuation")
    elif isinstance(obj, Combiner):
        file.write(b"#combiner")
    else:
        file.write(b"#unknown")

def _f_print_trace(file, continuation):
    assert isinstance(continuation, Continuation)
    # Output stack trace in reverse order, with recent calls last
    frames = []
    while continuation is not None:
        frames.append(continuation)
        continuation = continuation.parent
    while frames:
        continuation = frames.pop()
        # Skip helper frames (part of argument evaluation)
        if continuation._call_info is None:
            continue
        expr = continuation._call_info
        loc = LOCATIONS.get(expr)
        if loc is None:
            # Non-source expressions can be evaluated, usually from eval
            file.write(b"  in unknown\n")
            file.write(b"    ")
            _f_write(file, expr)
            file.write(b"\n")
            continue
        # Get source location of expression
        if loc.start_line_no == loc.end_line_no:
            line_info = b"%d" % (loc.start_line_no+1,)
        else:
            line_info = b"%d:%d" % (loc.start_line_no+1, loc.end_line_no+1)
        file.write(b"  in %s at %s [%d:%d]\n" % (loc.filename, line_info, loc.start_char_no+1, loc.end_char_no+1))
        # TODO: output the actual content of the lines the expression is from
        file.write(b"    ")
        _f_write(file, expr)
        file.write(b"\n")

def _f_format_syntax_error(file, error, filename, lines, starts_at=0):
    file.write(b"! --- syntax error ---\n")
    file.write(b"  in %s at %d [%d:]\n" % (filename, error.line_no + 1, error.char_no + 1))
    file.write(b"    ")
    file.write(lines[error.line_no - starts_at])
    file.write(b"\n")
    file.write(b"! syntax-error ")
    _f_write(file, String(_c_str_to_bytes(error.message)))
    file.write(b"\n")

def _f_format_evaluation_error(file, error):
    if error.parent is not None:
        file.write(b"! --- stack trace ---\n")
        _f_print_trace(file, error.parent)
    file.write(b"! error ")
    _f_write(file, error.value)
    file.write(b"\n")

# Location information is not stored on the object, so we need to create a new
# locations list with the objects in the immutable copy.
def _f_copy_immutable_and_locations(exprs, locations):
    old_locations = {}
    for expr, l1, c1, l2, c2 in locations:
        old_locations[expr] = (l1, c1, l2, c2)
    copies = []
    new_locations = []
    for expr in exprs:
        copy = _f_copy_immutable(expr)
        copies.append(copy)
        _transfer_locations(expr, copy, old_locations, new_locations)
    return copies, new_locations
def _transfer_locations(orig, copy, old_locations, new_locations):
    if orig not in old_locations:
        return
    l1, c1, l2, c2 = old_locations.pop(orig)
    new_locations.append((copy, l1, c1, l2, c2))
    if isinstance(orig, Pair):
        assert isinstance(copy, Pair)
        _transfer_locations(orig.car, copy.car, old_locations, new_locations)
        _transfer_locations(orig.cdr, copy.cdr, old_locations, new_locations)

# == Primitive combiners

# Pair unpacking helper functions (must specialize on call site since the
# return type differs based on rest=True/False.
@objectmodel.specialize.call_location()
def _unpack1(expr, message, rest=False):
    if not isinstance(expr, Pair): raise RuntimeError(message)
    if rest: return expr.car, expr.cdr
    if not isinstance(expr.cdr, Nil): raise RuntimeError(message)
    return expr.car
@objectmodel.specialize.call_location()
def _unpack2(expr, message, rest=False):
    arg1, expr = _unpack1(expr, message, rest=True)
    arg2, expr = _unpack1(expr, message, rest=True)
    if rest: return arg1, arg2, expr
    if not isinstance(expr, Nil): raise RuntimeError(message)
    return arg1, arg2
@objectmodel.specialize.call_location()
def _unpack3(expr, message, rest=False):
    arg1, expr = _unpack1(expr, message, rest=True)
    arg2, expr = _unpack1(expr, message, rest=True)
    arg3, expr = _unpack1(expr, message, rest=True)
    if rest: return arg1, arg2, arg3, expr
    if not isinstance(expr, Nil): raise RuntimeError(message)
    return arg1, arg2, arg3

# (number? expr)
def _operative_number(env, expr, parent):
    _ERROR = "expected (number? ANY)"
    number = _unpack1(expr, _ERROR)
    return f_return(parent, TRUE if isinstance(number, Int) else FALSE)

# (+ a b)
def _operative_plus(env, expr, parent):
    _ERROR = "expected (+ INT INT)"
    a, b = _unpack2(expr, _ERROR)
    if not isinstance(a, Int): raise RuntimeError(_ERROR)
    if not isinstance(b, Int): raise RuntimeError(_ERROR)
    return f_return(parent, Int(a.value + b.value))

# (* a b)
def _operative_times(env, expr, parent):
    _ERROR = "expected (* INT INT)"
    a, b = _unpack2(expr, _ERROR)
    if not isinstance(a, Int): raise RuntimeError(_ERROR)
    if not isinstance(b, Int): raise RuntimeError(_ERROR)
    return f_return(parent, Int(a.value * b.value))

# (<=? a b)
def _operative_less_equal(env, expr, parent):
    _ERROR = "expected (<=? INT INT)"
    a, b = _unpack2(expr, _ERROR)
    if not isinstance(a, Int): raise RuntimeError(_ERROR)
    if not isinstance(b, Int): raise RuntimeError(_ERROR)
    return f_return(parent, TRUE if a.value <= b.value else FALSE)

# (eq? a b)
def _eq(a, b):
    if False:
        pass
    elif isinstance(a, Nil):
        return isinstance(b, Nil)
    elif isinstance(a, Ignore):
        return isinstance(b, Ignore)
    elif isinstance(a, Inert):
        return isinstance(b, Inert)
    elif isinstance(a, Boolean):
        return isinstance(b, Boolean) and a.value == b.value
    elif isinstance(a, Int):
        return isinstance(b, Int) and a.value == b.value
    elif isinstance(a, Symbol):
        return isinstance(b, Symbol) and a.name == b.name
    elif isinstance(a, String):
        return isinstance(b, String) and a.value == b.value
    else:
        return a is b
def _operative_eq(env, expr, parent):
    _ERROR = "expected (eq? ANY ANY)"
    a, b = _unpack2(expr, _ERROR)
    return f_return(parent, TRUE if _eq(a, b) else FALSE)

# (pair? expr)
def _operative_pair(env, expr, parent):
    _ERROR = "expected (pair? ANY)"
    pair = _unpack1(expr, _ERROR)
    return f_return(parent, TRUE if isinstance(pair, Pair) else FALSE)

# (cons a b)
def _operative_cons(env, expr, parent):
    _ERROR = "expected (cons ANY ANY)"
    a, b = _unpack2(expr, _ERROR)
    return f_return(parent, MutablePair(a, b))

# (car pair)
def _operative_car(env, expr, parent):
    _ERROR = "expected (car PAIR)"
    pair = _unpack1(expr, _ERROR)
    if not isinstance(pair, Pair): raise RuntimeError(_ERROR)
    return f_return(parent, pair.car)

# (cdr pair)
def _operative_cdr(env, expr, parent):
    _ERROR = "expected (cdr PAIR)"
    pair = _unpack1(expr, _ERROR)
    if not isinstance(pair, Pair): raise RuntimeError(_ERROR)
    return f_return(parent, pair.cdr)

# (equal? a b)
def _equal_recursively_set(a, b, visited):
    if not isinstance(a, Pair) or not isinstance(b, Pair):
        return _eq(a, b)
    # a and b are pairs
    if (a, b) in visited:
        return True
    visited[(a, b)] = True
    if not _equal_recursively_set(a.car, b.car, visited):
        return False
    if not _equal_recursively_set(a.cdr, b.cdr, visited):
        return False
    visited.pop((a, b))
    return True
def _equal(a, b):
    return _equal_recursively_set(a, b, {})
def _operative_equal(env, expr, parent):
    _ERROR = "expected (equal? ANY ANY)"
    a, b = _unpack2(expr, _ERROR)
    return f_return(parent, TRUE if _equal(a, b) else FALSE)

# (set-car! pair car)
def _operative_set_car(env, expr, parent):
    _ERROR = "expected (set-car! MUTABLE-PAIR ANY)"
    pair, car = _unpack2(expr, _ERROR)
    if not isinstance(pair, MutablePair): raise RuntimeError(_ERROR)
    pair.car = car
    return f_return(parent, INERT)

# (set-cdr! pair cdr)
def _operative_set_cdr(env, expr, parent):
    _ERROR = "expected (set-cdr! MUTABLE-PAIR ANY)"
    pair, cdr = _unpack2(expr, _ERROR)
    if not isinstance(pair, MutablePair): raise RuntimeError(_ERROR)
    pair.cdr = cdr
    return f_return(parent, INERT)

# (operative? expr)
def _operative_operative(env, expr, parent):
    _ERROR = "expected (operative? ANY)"
    combiner = _unpack1(expr, _ERROR)
    return f_return(parent, TRUE if isinstance(combiner, Combiner) and combiner.num_wraps <= 0 else FALSE)

# ($vau (dyn args) expr)
def _operative_vau(env, expr, parent):
    _ERROR = "expected ($vau (PARAM PARAM) ANY)"
    envname_name, body = _unpack2(expr, _ERROR)
    envname, name = _unpack2(envname_name, _ERROR)
    if not isinstance(envname, Symbol) and not isinstance(envname, Ignore): raise RuntimeError(_ERROR)
    immutable_name = _f_copy_immutable(name)
    immutable_body = _f_copy_immutable(body)
    return f_return(parent, Combiner(0, UserDefinedOperative(env, envname, immutable_name, immutable_body)))

# (applicative? expr)
def _operative_applicative(env, expr, parent):
    _ERROR = "expected (applicative? ANY)"
    combiner = _unpack1(expr, _ERROR)
    return f_return(parent, TRUE if isinstance(combiner, Combiner) and combiner.num_wraps > 0 else FALSE)

# (wrap combiner)
def _operative_wrap(env, expr, parent):
    _ERROR = "expected (wrap COMBINER)"
    combiner = _unpack1(expr, _ERROR)
    if not isinstance(combiner, Combiner): raise RuntimeError(_ERROR)
    return f_return(parent, Combiner(combiner.num_wraps + 1, combiner.operative))

# (unwrap combiner)
def _operative_unwrap(env, expr, parent):
    _ERROR = "expected (unwrap COMBINER)"
    combiner = _unpack1(expr, _ERROR)
    if not isinstance(combiner, Combiner): raise RuntimeError(_ERROR)
    if combiner.num_wraps == 0: raise RuntimeError(_ERROR)
    return f_return(parent, Combiner(combiner.num_wraps - 1, combiner.operative))

# (environment? expr)
def _operative_environment(env, expr, parent):
    _ERROR = "expected (environment? ANY)"
    operative = _unpack1(expr, _ERROR)
    return f_return(parent, TRUE if isinstance(operative, Environment) else FALSE)

# (eval env expr)
def _operative_eval(env, expr, parent):
    _ERROR = "expected (eval ENVIRONMENT ANY)"
    environment, expression = _unpack2(expr, _ERROR)
    if not isinstance(environment, Environment): raise RuntimeError(_ERROR)
    return f_eval(environment, expression, parent)

# ($remote-eval env expr)
def _f_remote_eval(static, value, parent):
    assert isinstance(static, FRemoteEvalEnvironment)
    expression = static.expression
    if not isinstance(value, Environment):
        raise RuntimeError("expected environment argument value")
    if parent is not None:
        parent = Continuation(parent.env, parent.operative, parent.parent)
        parent._call_info = expression
    return f_eval(value, expression, parent)
_F_REMOTE_EVAL = PrimitiveOperative(_f_remote_eval)
def _operative_remote_eval(env, expr, parent):
    _ERROR = "expected ($remote-eval ENVIRONMENT ANY)"
    environment, expression = _unpack2(expr, _ERROR)
    next_env = FRemoteEvalEnvironment(expression)
    next_continuation = Continuation(next_env, _F_REMOTE_EVAL, parent)
    next_continuation._call_info = environment
    return f_eval(env, environment, next_continuation)

# (make-environment [parent])
def _operative_make_environment(env, expr, parent):
    _ERROR = "expected (make-environment [ENVIRONMENT])"
    if isinstance(expr, Nil):
        environment = None
    else:
        environment = _unpack1(expr, _ERROR)
        if not isinstance(environment, Environment): raise RuntimeError(_ERROR)
    return f_return(parent, Environment({}, environment))

# (symbol? expr)
def _operative_symbol(env, expr, parent):
    _ERROR = "expected (symbol? ANY)"
    symbol = _unpack1(expr, _ERROR)
    return f_return(parent, TRUE if isinstance(symbol, Symbol) else FALSE)

# ($define! name value)
def _define_recursively_set(env, name, value, visited_names, visited_pairs):
    if isinstance(name, Ignore):
        return
    if isinstance(name, Nil):
        if not isinstance(value, Nil):
            raise RuntimeError("parameter tree could not be matched to value")
        return
    if isinstance(name, Symbol):
        if name.name in visited_names:
            raise RuntimeError("parameter tree symbol occurs more than once")
        visited_names[name.name] = True
        _environment_update(env, name, value)
        return
    if isinstance(name, Pair):
        if name in visited_pairs:
            raise RuntimeError("parameter tree consists of self-referencing pairs")
        visited_pairs[name] = True
        if not isinstance(value, Pair):
            raise RuntimeError("parameter tree could not be matched to value")
        _define_recursively_set(env, name.car, value.car, visited_names, visited_pairs)
        _define_recursively_set(env, name.cdr, value.cdr, visited_names, visited_pairs)
        visited_pairs.pop(name)
        return
    raise RuntimeError("parameter tree consists of invalid types")
@jit.unroll_safe
def _define_recursively_list(env, name, value, visited_names, visited_pairs):
    if isinstance(name, Ignore):
        return
    if isinstance(name, Nil):
        if not isinstance(value, Nil):
            raise RuntimeError("parameter tree could not be matched to value")
        return
    if isinstance(name, Symbol):
        for visited_name in visited_names:
            if name.name == visited_name:
                raise RuntimeError("parameter tree symbol occurs more than once")
        visited_names.append(name.name)
        _environment_update(env, name, value)
        return
    if isinstance(name, Pair):
        for visited_pair in visited_pairs:
            if name is visited_pair:
                raise RuntimeError("parameter tree consists of self-referencing pairs")
        visited_pairs.append(name)
        if not isinstance(value, Pair):
            raise RuntimeError("parameter tree could not be matched to value")
        _define_recursively_list(env, name.car, value.car, visited_names, visited_pairs)
        _define_recursively_list(env, name.cdr, value.cdr, visited_names, visited_pairs)
        visited_pairs.pop()
        return
    raise RuntimeError("parameter tree consists of invalid types")
@jit.unroll_safe
def _define_recursively_check(name, visited_names, visited_pairs):
    if isinstance(name, Ignore):
        return
    if isinstance(name, Nil):
        return
    if isinstance(name, Symbol):
        for visited_name in visited_names:
            if name.name == visited_name:
                return "parameter tree symbol occurs more than once"
        visited_names.append(name.name)
        return
    if isinstance(name, Pair):
        for visited_pair in visited_pairs:
            if name is visited_pair:
                return "parameter tree consists of self-referencing pairs"
        visited_pairs.append(name)
        _define_recursively_check(name.car, visited_names, visited_pairs)
        _define_recursively_check(name.cdr, visited_names, visited_pairs)
        visited_pairs.pop()
        return
    return "parameter tree consists of invalid types"
def _define_recursively_nocheck(env, name, value):
    if isinstance(name, Ignore):
        return
    if isinstance(name, Nil):
        if not isinstance(value, Nil):
            raise RuntimeError("parameter tree could not be matched to value")
        return
    if isinstance(name, Symbol):
        _environment_update(env, name, value)
        return
    if isinstance(name, Pair):
        if not isinstance(value, Pair):
            raise RuntimeError("parameter tree could not be matched to value")
        _define_recursively_nocheck(env, name.car, value.car)
        _define_recursively_nocheck(env, name.cdr, value.cdr)
        return
    raise RuntimeError("parameter tree consists of invalid types")
@jit.elidable
def _define_check_valid_elidable(name):
    return _define_recursively_check(name, [], [])
def _define(env, name, value):
    if not jit.we_are_jitted():
        _define_recursively_set(env, name, value, {}, {})
    elif jit.isvirtual(name) or isinstance(name, MutablePair):
        _define_recursively_list(env, name, value, [], [])
    else:
        message = _define_check_valid_elidable(name)
        if message is not None:
            raise RuntimeError(message)
        _define_recursively_nocheck(env, name, value)
def _f_define(static, value, parent):
    assert isinstance(static, FDefineEnvironment)
    env = static.env
    assert isinstance(env, Environment)
    name = static.name
    _define(env, name, value)
    return f_return(parent, INERT)
_F_DEFINE = PrimitiveOperative(_f_define)
def _operative_define(env, expr, parent):
    _ERROR = "expected ($define! PARAM ANY)"
    name, value = _unpack2(expr, _ERROR)
    next_env = FDefineEnvironment(env, name)
    next_continuation = Continuation(next_env, _F_DEFINE, parent)
    next_continuation._call_info = value
    return f_eval(env, value, next_continuation)

# ($if cond then orelse)
def _f_if(static, result, parent):
    assert isinstance(static, FIfEnvironment)
    env = static.env
    if not isinstance(result, Boolean):
        raise RuntimeError("expected boolean test value")
    if result.value:
        then = static.then
        return f_eval(env, then, parent)
    else:
        orelse = static.orelse
        return f_eval(env, orelse, parent)
_F_IF = PrimitiveOperative(_f_if)
def _operative_if(env, expr, parent):
    _ERROR = "expected ($if ANY ANY ANY)"
    cond, then, orelse = _unpack3(expr, _ERROR)
    next_env = FIfEnvironment(env, then, orelse)
    next_continuation = Continuation(next_env, _F_IF, parent)
    next_continuation._call_info = cond
    return f_eval(env, cond, next_continuation)

# ($binds? env name)
def _f_binds(static, value, parent):
    assert isinstance(static, FBindsEnvironment)
    name = static.name
    if not isinstance(value, Environment):
        raise RuntimeError("expected environment argument value")
    found = _environment_lookup(value, name)
    if found is None:
        return f_return(parent, FALSE)
    return f_return(parent, TRUE)
_F_BINDS = PrimitiveOperative(_f_binds)
def _operative_binds(env, expr, parent):
    _ERROR = "expected ($binds? ENV SYMBOL)"
    env_expr, name = _unpack2(expr, _ERROR)
    if not isinstance(name, Symbol): raise RuntimeError(_ERROR)
    next_env = FBindsEnvironment(name)
    next_continuation = Continuation(next_env, _F_BINDS, parent)
    next_continuation._call_info = env_expr
    return f_eval(env, env_expr, next_continuation)

# (continuation? expr)
def _operative_continuation(env, expr, parent):
    _ERROR = "expected (continuation? ANY)"
    continuation = _unpack1(expr, _ERROR)
    return f_return(parent, TRUE if isinstance(continuation, Continuation) else FALSE)

# (call/cc combiner)
def _operative_call_cc(env, expr, parent):
    _ERROR = "expected (call/cc COMBINER)"
    combiner = _unpack1(expr, _ERROR)
    if not isinstance(combiner, Combiner): raise RuntimeError(_ERROR)
    # return f_eval(env, MutablePair(combiner, MutablePair(parent, NIL)), parent)
    next_continuation = Continuation(env, combiner.operative, parent)
    return f_return(next_continuation, MutablePair(parent, NIL))

# (continuation->applicative continuation)
def _operative_continuation_to_applicative(env, expr, parent):
    _ERROR = "expected (continuation->applicative CONTINUATION)"
    continuation = _unpack1(expr, _ERROR)
    if not isinstance(continuation, Continuation): raise RuntimeError(_ERROR)
    return f_return(parent, Combiner(1, ContinuationOperative(continuation)))

# (extend-continuation continuation applicative environment)
def _operative_extend_continuation(env, expr, parent):
    _ERROR = "expected (extend-continuation CONTINUATION STRICT-APPLICATIVE ENVIRONMENT)"
    continuation, applicative, environment = _unpack3(expr, _ERROR)
    if not isinstance(continuation, Continuation): raise RuntimeError(_ERROR)
    if not isinstance(applicative, Combiner) or applicative.num_wraps != 1: raise RuntimeError(_ERROR)
    if not isinstance(environment, Environment): raise RuntimeError(_ERROR)
    return f_return(parent, Continuation(environment, applicative.operative, continuation))

# (string? expr)
def _operative_string(env, expr, parent):
    _ERROR = "expected (string? ANY)"
    string = _unpack1(expr, _ERROR)
    return f_return(parent, TRUE if isinstance(string, String) else FALSE)

def _primitive(num_wraps, func):
    return Combiner(num_wraps, PrimitiveOperative(func))
_DEFAULT_ENV = {
    b"number?": _primitive(1, _operative_number),
    b"+": _primitive(1, _operative_plus),
    b"*": _primitive(1, _operative_times),
    b"<=?": _primitive(1, _operative_less_equal),
    b"eq?": _primitive(1, _operative_eq),
    b"pair?": _primitive(1, _operative_pair),
    b"cons": _primitive(1, _operative_cons),
    b"car": _primitive(1, _operative_car),
    b"cdr": _primitive(1, _operative_cdr),
    b"equal?": _primitive(1, _operative_equal),
    b"set-car!": _primitive(1, _operative_set_car),
    b"set-cdr!": _primitive(1, _operative_set_cdr),
    b"operative?": _primitive(1, _operative_operative),
    b"$vau": _primitive(0, _operative_vau),
    b"applicative?": _primitive(1, _operative_applicative),
    b"wrap": _primitive(1, _operative_wrap),
    b"unwrap": _primitive(1, _operative_unwrap),
    b"environment?": _primitive(1, _operative_environment),
    b"eval": _primitive(1, _operative_eval),
    b"$remote-eval": _primitive(0, _operative_remote_eval),
    b"make-environment": _primitive(1, _operative_make_environment),
    b"symbol?": _primitive(1, _operative_symbol),
    b"$define!": _primitive(0, _operative_define),
    b"$if": _primitive(0, _operative_if),
    b"$binds?": _primitive(0, _operative_binds),
    b"continuation?": _primitive(1, _operative_continuation),
    b"call/cc": _primitive(1, _operative_call_cc),
    b"continuation->applicative": _primitive(1, _operative_continuation_to_applicative),
    b"extend-continuation": _primitive(1, _operative_extend_continuation),
    b"error-continuation": ERROR_CONT,
    b"string?": _primitive(1, _operative_string),
    b"$jit-loop-head": Combiner(0, _F_LOOP_HEAD),
}

# == Entry point

def main(argv):
    import os
    # Configure JIT to allow larger traces (copied from pycket's entry_point.py)
    jit.set_param(None, "trace_limit", 1000000)
    jit.set_param(None, "threshold", 131)
    jit.set_param(None, "trace_eagerness", 50)
    jit.set_param(None, "max_unroll_loops", 15)
    user_config_string = os.environ.get("RFEXPROTO_JIT_CONFIG")
    if user_config_string is not None:
        jit.set_user_param(None, user_config_string)

    stdin = stdout = stderr = None
    file = None
    filename = None
    interactive = False

    # TODO: look into optparse
    if len(argv) >= 2 and argv[1] == "-i":
        argv.pop(1)
        interactive = True
    if len(argv) >= 2 and argv[1] == "--":
        argv.pop(1)
    if len(argv) == 2:
        filename = _c_str_to_bytes(argv[1])
        file = rfile.create_file(filename)
    elif len(argv) == 1:
        stdin, stdout, stderr = rfile.create_stdio()
        # For some reason, os.isatty(0) won't compile here
        if stdin.isatty():
            interactive = True
        elif not interactive:
            filename = b"<stdin>"
            file = stdin
    else:
        stdin, stdout, stderr = rfile.create_stdio()
        stdout.write(b"error: unknown arguments\n")
        return 2

    env = None
    if file is not None:
        # Read whole file
        parts = []
        while True:
            part = file.read(2048)
            if not part: break
            parts.append(part)
        text = b"".join(parts)
        # Lex and parse
        try:
            offsets = []
            tokens = tokenize(text, offsets=offsets)
            tokens.reverse()
            offsets.reverse()
            exprs = []
            while tokens:
                expr_locations = []
                expr = parse(tokens, offsets=offsets, locations=expr_locations, upcons={})
                [expr], copy_locations = _f_copy_immutable_and_locations([expr], expr_locations)
                exprs.append(expr)
                for expr, l1, c1, l2, c2 in copy_locations:
                    LOCATIONS.set(expr, Location(filename, l1, c1, l2, c2))
        except ParsingError as e:
            if stderr is None:
                stdin, stdout, stderr = rfile.create_stdio()
            _f_format_syntax_error(stderr, e, filename, text.split(b"\n"))
            stderr.flush()
            if not interactive:
                return 1
        else:
            # Setup standard environment
            env = Environment({}, Environment(_DEFAULT_ENV, None))
            # Evaluate expressions and write their results
            for expr in exprs:
                state = _f_toplevel_eval(env, expr)
                try:
                    value = fully_evaluate(state)
                    if not isinstance(value, Inert):
                        if stdout is None:
                            stdin, stdout, stderr = rfile.create_stdio()
                        _f_write(stdout, value)
                        stdout.write(b"\n")
                        stdout.flush()
                except EvaluationError as e:
                    if stderr is None:
                        stdin, stdout, stderr = rfile.create_stdio()
                    _f_format_evaluation_error(stderr, e)
                    stderr.flush()
                    if not interactive:
                        return 1
                    break

    # Start REPL if no args and is TTY or if -i flag was passed
    if interactive:
        # REPL prompts
        PROMPT_1 = b"rf> "  # default prompt
        PROMPT_2 = b"... "  # multi-line prompt
        prompt_list = [PROMPT_1]
        # Setup standard environment
        if env is None:
            env = Environment({}, Environment(_DEFAULT_ENV, None))
        # Parser state
        lines = []
        parser = _InteractiveParser()
        # Read STDIN lines one by one
        if stdin is None:
            stdin, stdout, stderr = rfile.create_stdio()
        for line in _prompt_lines(stdin, stdout, prompt_list):
            # Attempt to lex and parse
            try:
                expr_locations = []
                done, exprs = parser.handle(line, lines=lines, locations=expr_locations)
                exprs, copy_locations = _f_copy_immutable_and_locations(exprs, expr_locations)
                for expr, l1, c1, l2, c2 in copy_locations:
                    LOCATIONS.set(expr, Location(b"<stdin>", l1, c1, l2, c2))
            except ParsingError as e:
                _f_format_syntax_error(stderr, e, b"<stdin>", parser.last_lines, starts_at=len(lines))
                stderr.flush()
                prompt_list[0] = PROMPT_1
                continue
            if not done:
                prompt_list[0] = PROMPT_2
                continue
            # Evaluate expressions and write their results
            try:
                for expr in exprs:
                    state = _f_toplevel_eval(env, expr)
                    value = fully_evaluate(state)
                    if not isinstance(value, Inert):
                        _f_write(stdout, value)
                        stdout.write(b"\n")
                        stdout.flush()
            except EvaluationError as e:
                _f_format_evaluation_error(stderr, e)
                stderr.flush()
            prompt_list[0] = PROMPT_1

    return 0

# RPython toolchain
def target(driver, args):
    driver.exe_name = __name__ + "-c"
    if driver.config.translation.jit:
        driver.exe_name += "-jit"
    return main, None
def jitpolicy(driver):
    from rpython.jit.codewriter.policy import JitPolicy
    return JitPolicy()

# Python script
if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
