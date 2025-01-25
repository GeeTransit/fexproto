from __future__ import print_function

# Optional RPython imports
try:
    from rpython.rlib.rsre import rsre_re as re
    from rpython.rlib import jit
    from rpython.rlib import objectmodel
except ImportError:
    import re
    class jit(object):
        class JitDriver(object):
            def __init__(self, **kwargs): pass
            def jit_merge_point(self, **kwargs): pass
            def can_enter_jit(self, **kwargs): pass
        @staticmethod
        def set_param(*args): pass
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
    class objectmodel(object):
        class specialize(object):
            @staticmethod
            def call_location(): return lambda func: func

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
        assert isinstance(value, str)
        self.value = value
class Symbol(Object):
    _attrs_ = _immutable_fields_ = ("name",)
    def __init__(self, name):
        assert isinstance(name, str)
        self.name = name
class Environment(Object):
    _attrs_ = _immutable_fields_ = ("storage", "parent", "localmap", "version", "children")
    def __init__(self, bindings, parent):
        assert parent is None or isinstance(parent, Environment)
        storage, localmap = _environment_tostoragemap(bindings)
        self.storage = storage
        self.parent = parent
        self.localmap = localmap
        self.version = VersionTag()
        self.children = None
        _environment_addchild(parent, self)
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
    _attrs_ = _immutable_fields_ = ("num_wraps", "operative")
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
            return f_error(parent, MutablePair(String(e.message), NIL))
class UserDefinedOperative(Operative):
    _immutable_ = True
    def __init__(self, env, envname, name, body):
        assert env is None or isinstance(env, Environment)
        self.env = env
        assert isinstance(envname, Symbol) or isinstance(envname, Ignore)
        self.envname = envname
        assert isinstance(name, Symbol) or isinstance(name, Ignore)
        self.name = name
        assert not isinstance(body, MutablePair)
        self.body = body
    def call(self, env, value, parent):
        call_env = Environment({}, self.env)
        envname = self.envname
        if isinstance(envname, Symbol):
            _environment_update(call_env, envname, env)
        name = self.name
        if isinstance(name, Symbol):
            _environment_update(call_env, name, value)
        return f_eval(call_env, self.body, parent)

def _f_noop(env, expr, parent):
    return f_return(parent, expr)
NOOP = PrimitiveOperative(_f_noop)

def _f_copy_immutable(expr):
    if not isinstance(expr, MutablePair):
        return expr
    # TODO: when mutation is introduced, support self-referencing structures
    car = _f_copy_immutable(expr.car)
    cdr = _f_copy_immutable(expr.cdr)
    return ImmutablePair(car, cdr)

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
class LocalMap(object):
    _attrs_ = _immutable_fields_ = ("transitions", "indexes")
    def __init__(self):
        self.transitions = {}  # str -> LocalMap
        self.indexes = {}  # str -> int
    @jit.elidable
    def find(self, name):
        return self.indexes.get(name, -1)
    @jit.elidable
    def new_localmap_with(self, name):
        assert isinstance(name, str)
        if name not in self.transitions:
            new = LocalMap()
            new.indexes.update(self.indexes)
            new.indexes[name] = len(self.indexes)
            self.transitions[name] = new
        return self.transitions[name]
_ROOT_LOCALMAP = LocalMap()

class VersionTag(object):
    _attrs_ = _immutable_fields_ = ()

@jit.unroll_safe
def _environment_tostoragemap(bindings):
    storage = []
    localmap = _ROOT_LOCALMAP
    if bindings is not None and len(bindings) > 0:
        for key, value in bindings.items():  # TODO: should we sort?
            localmap = localmap.new_localmap_with(key)
            storage.append(value)
    return storage, localmap

def _environment_addchild(parent, env):
    if parent is not None and parent.children is None:
        # First time the parent environment has a child
        parent.children = []
        if parent.parent is not None:
            # Make grandparent hold weakref to parent. Versions only need to be
            # updated for environments with children.
            if parent.parent.children is None:
                raise RuntimeError("env parent invariant broken?")
            import weakref
            parent.parent.children.append(weakref.ref(parent))

def _environment_lookup(env, name):
    # TODO: which promotes are actually necessary for performance?
    name_name = name.name
    if not jit.isvirtual(name_name):
        jit.promote_string(name_name)
    if env is None:
        return None
    if not jit.isvirtual(env) and not jit.isvirtual(env.localmap):
        jit.promote(env.localmap)
    index = env.localmap.find(name_name)
    if index >= 0:
        return env.storage[index]
    env = env.parent
    if env is None:
        return None
    if not jit.isvirtual(env):
        jit.promote(env)
        if not jit.isvirtual(env.version):
            jit.promote(env.version)
    return _environment_lookup_version(env, name_name, env.version)

@jit.elidable
def _environment_lookup_version(env, name_name, version):
    while env is not None:
        index = env.localmap.find(name_name)
        if index >= 0:
            return env.storage[index]
        env = env.parent
    return None

def _environment_update(env, name, value):
    name_name = name.name
    index = env.localmap.find(name_name)
    if index >= 0:
        env.storage[index] = value
    else:
        env.localmap = env.localmap.new_localmap_with(name_name)
        env.storage.append(value)
    _environment_update_version(env, VersionTag())

@jit.unroll_safe
def _environment_update_version(env, version):
    env.version = version
    if env.children is not None:
        cleanup = False
        for child in env.children:
            child_env = child()
            if child_env is not None:
                _environment_update_version(child_env, version)
            else:
                cleanup = True
        if cleanup:
            i = 0
            for i in range(len(env.children)):
                if env.children[i]() is None:
                    break
            j = i
            for i in range(i, len(env.children)):
                if env.children[i]() is None:
                    continue
                env.children[i], env.children[j] = env.children[j], env.children[i]
                j += 1
            del env.children[j:]

# Specialized environments

class StepWrappedEnvironment(Environment):
    _attrs_ = Environment._attrs_ + ("env", "args")
    _immutable_fields_ = Environment._immutable_fields_
    def __init__(self, env, args):
        Environment.__init__(self, None, None)
        self.env = env
        self.args = args
class StepEvCarEnvironment(Environment):
    _attrs_ = Environment._attrs_ + ("env", "operative", "num_wraps", "todo", "p", "i", "res")
    _immutable_fields_ = Environment._immutable_fields_
    def __init__(self, env, operative, num_wraps, todo, p, i, res):
        Environment.__init__(self, None, None)
        self.env = env
        self.operative = operative
        self.num_wraps = num_wraps
        self.todo = todo
        self.p = p
        self.i = i
        self.res = res
class FRemoteEvalEnvironment(Environment):
    _attrs_ = Environment._attrs_ + ("expression",)
    _immutable_fields_ = Environment._immutable_fields_
    def __init__(self, expression):
        Environment.__init__(self, None, None)
        self.expression = expression
class FIfEnvironment(Environment):
    _attrs_ = Environment._attrs_ + ("env", "then", "orelse")
    _immutable_fields_ = Environment._immutable_fields_
    def __init__(self, env, then, orelse):
        Environment.__init__(self, None, None)
        self.env = env
        self.then = then
        self.orelse = orelse
class FDefineEnvironment(Environment):
    _attrs_ = Environment._attrs_ + ("env", "name")
    _immutable_fields_ = Environment._immutable_fields_
    def __init__(self, env, name):
        Environment.__init__(self, None, None)
        self.env = env
        self.name = name
class FBindsEnvironment(Environment):
    _attrs_ = Environment._attrs_ + ("name",)
    _immutable_fields_ = Environment._immutable_fields_
    def __init__(self, name):
        Environment.__init__(self, None, None)
        self.name = name

# Core interpreter logic

def f_return(parent, obj):
    return None, obj, parent
def f_return_loop_constant(parent, obj):
    return obj, None, parent
def f_error(parent, value):
    # TODO: replace with abnormal pass when guarded continuations implemented
    return f_return(ERROR_CONT, MutablePair(parent, value))
def f_eval(env, obj, parent=None):
    return obj, env, parent

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
            return f_error(parent, MutablePair(String("binding not found"), MutablePair(obj, NIL)))
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
    assert isinstance(combiner, Combiner)
    if combiner.num_wraps == 0 or isinstance(args, Nil):
        return f_return(Continuation(env, combiner.operative, parent), args)
    c = args; p = 0
    while isinstance(c, Pair): p += 1; c = c.cdr
    assert p > 0
    if not isinstance(c, Nil):
        raise RuntimeError("applicative call args must be proper list")
    assert isinstance(args, Pair)
    next_expr = args.car
    next_env = StepEvCarEnvironment(env, combiner.operative, combiner.num_wraps, args.cdr, p, 0, NIL)
    next_continuation = Continuation(next_env, _STEP_CALL_EVCAR, parent)
    next_continuation._call_info = next_expr
    state = f_eval(env, next_expr, next_continuation)
    if jit.isvirtual(next_expr):
        state = step_evaluate(state)
    return state
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
    assert todo is NIL or isinstance(todo, Pair)
    p = static.p
    assert isinstance(p, int)
    i = static.i
    assert isinstance(i, int)
    res = static.res
    assert res is NIL or isinstance(res, Pair)
    res = Pair(value, res)
    i = i + 1
    if i == p:
        i = 0
        num_wraps = num_wraps - 1
        assert todo is NIL
        for _ in range(p): assert isinstance(res, Pair); todo = Pair(res.car, todo); res = res.cdr
        assert isinstance(todo, Pair)
        if num_wraps == 0:
            continuation = Continuation(env, operative, parent)
            return f_return(continuation, todo)
    assert isinstance(todo, Pair)
    next_env = StepEvCarEnvironment(env, operative, num_wraps, todo.cdr, p, i, res)
    next_expr = todo.car
    next_continuation = Continuation(next_env, _STEP_CALL_EVCAR, parent)
    next_continuation._call_info = next_expr
    state = f_eval(env, next_expr, next_continuation)
    if jit.isvirtual(next_expr):
        state = step_evaluate(state)
    return state
_STEP_CALL_EVCAR = PrimitiveOperative(_step_call_evcar)

# == Lexing, parsing, and writing logic

_TOKEN_PATTERN = re.compile("|".join([
    r'[()]',  # open and close brackets
    r'[^ \t\r\n();"]+',  # symbol-like tokens
    r'"(?:[^"\\\r\n]|\\[^\r\n])*"',  # single-line strings
    r'[ \t\r]+',  # horizontal whitespace
    r'\n',  # newline (parsed separately to count lines)
    r';[^\r\n]*',  # single-line comments
]))
def tokenize(text, offsets=None):
    result = []
    i = 0
    len_text = len(text)
    line_no = 0
    line_start_i = 0
    while i < len_text:
        match = _TOKEN_PATTERN.match(text, i)
        if match is None:
            raise ParsingError("unknown syntax", line_no, i - line_start_i)
        token = match.group()
        if token == "\n":
            line_no += 1
            line_start_i = i + 1
        elif token[0] not in " \t\r;":
            result.append(token)
            if offsets is not None:
                offsets.append(line_no)
                offsets.append(i - line_start_i)
        i = match.end()
    return result

_STRING_PATTERN = re.compile("|".join([
    r'[^\\]',  # normal characters
    r'\\x[a-fA-F0-9][a-fA-F0-9]',  # hex escape sequence
    r'\\[abtnr"\\]',  # common escape sequences
]))
def parse(tokens, offsets=None, locations=None):
    token = tokens.pop()
    line_no = offsets.pop() if offsets is not None else -1
    char_no = offsets.pop() if offsets is not None else -1
    if token == ")":
        raise ParsingError("unmatched close bracket", line_no, char_no)
    if token == "(":
        expr, _, _ = _parse_elements(
            tokens,
            offsets=offsets, locations=locations,
            line_no=line_no, char_no=char_no,
            first_line_no=line_no, first_char_no=char_no,
        )
        return expr
    if token == "#t" or token == "#T":
        return TRUE
    if token == "#f" or token == "#F":
        return FALSE
    if token.lower() == "#ignore":
        return IGNORE
    if token.lower() == "#inert":
        return INERT
    if token[0] == '"':
        i = 1
        len_token = len(token) - 1
        chars = []
        while i < len_token:
            match = _STRING_PATTERN.match(token, i)
            if match is None:
                raise ParsingError("unknown string escape", line_no, char_no + i)
            part = match.group()
            if part[0] != "\\":
                chars.append(part[0])
            elif part[1] == "x":
                chars.append(chr(int(part[2]+part[3], 16)))
            else:
                chars.append('\a\b\t\n\r"\\'['abtnr"\\'.find(part[1])])
            i = match.end()
        return String("".join(chars))
    if token[0].isdigit() or token[0] in "+-" and len(token) > 1 and token[1].isdigit():
        return Int(int(token))
    if token[0] != "#":
        symbol = Symbol(token.lower())
        if locations is not None:
            locations.append((symbol, line_no, char_no, line_no, char_no + len(token)))
        return symbol
    raise ParsingError("unknown token", line_no, char_no)

def _parse_elements(
    tokens,
    offsets=None, locations=None,
    line_no=-1, char_no=-1,
    first_line_no=-1, first_char_no=-1,
):
    token = tokens[-1]
    if token == ")":
        tokens.pop()
        end_line_no = offsets.pop() if offsets is not None else -1
        end_char_no = offsets.pop() if offsets is not None else -1
        return NIL, end_line_no, end_char_no
    if token == ".":
        tokens.pop()
        if offsets is not None:
            offsets.pop()
            offsets.pop()
        if tokens[-1] == ")":
            line_no = offsets[-1] if offsets is not None else -1
            char_no = offsets[-2] if offsets is not None else -1
            raise ParsingError("unexpected close bracket", line_no, char_no)
        element = parse(tokens, offsets=offsets, locations=locations)
        end_line_no = offsets.pop() if offsets is not None else -1
        end_char_no = offsets.pop() if offsets is not None else -1
        if tokens.pop() != ")":
            raise ParsingError("expected close bracket", end_line_no, end_char_no)
        return element, end_line_no, end_char_no
    element = parse(tokens, offsets=offsets, locations=locations)
    if not tokens:
        raise ParsingError("unmatched open bracket", first_line_no, first_char_no)
    next_line_no = offsets[-1] if offsets is not None else -1
    next_char_no = offsets[-2] if offsets is not None else -1
    rest, end_line_no, end_char_no = _parse_elements(
        tokens,
        offsets=offsets, locations=locations,
        line_no=next_line_no, char_no=next_char_no,
        first_line_no=first_line_no, first_char_no=first_char_no,
    )
    pair = ImmutablePair(element, rest)
    if locations is not None:
        locations.append((pair, line_no, char_no, end_line_no, end_char_no + 1))
    return pair, end_line_no, end_char_no

def _f_write(obj):
    if isinstance(obj, Nil):
        print("()", end="")
    elif isinstance(obj, Int):
        print(str(obj.value), end="")
    elif isinstance(obj, String):
        print('"', end="")
        for char in obj.value:
            code = ord(char)
            if char in '\a\b\t\n\r"\\':  # escape sequences
                print("\\"+'abtnr"\\'['\a\b\t\n\r"\\'.find(char)], end="")
            elif not 32 <= code < 128:  # unprintable codes
                print("\\x"+"0123456789abcdef"[code//16]+"0123456789abcdef"[code%16], end="")
            else:
                print(char, end="")
        print('"', end="")
    elif isinstance(obj, Symbol):
        print(obj.name, end="")
    elif isinstance(obj, Ignore):
        print("#ignore", end="")
    elif isinstance(obj, Inert):
        print("#inert", end="")
    elif isinstance(obj, Boolean):
        if obj.value:
            print("#t", end="")
        else:
            print("#f", end="")
    elif isinstance(obj, Pair):
        print("(", end="")
        _f_write(obj.car)
        obj_cdr = obj.cdr
        while isinstance(obj_cdr, Pair):
            obj = obj_cdr
            print(" ", end="")
            _f_write(obj.car)
            obj_cdr = obj.cdr
        if not isinstance(obj_cdr, Nil):
            print(" . ", end="")
            _f_write(obj_cdr)
        print(")", end="")
    else:
        print("#unknown", end="")

def _f_print_trace(continuation, sources=None):
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
        if expr not in sources:
            # Non-source expressions can be evaluated, usually from eval
            print("  in unknown")
            print("    ", end="")
            _f_write(expr)
            print()
            continue
        # Get source location of expression
        filename, start_line_no, start_char_no, end_line_no, end_char_no = sources[expr]
        if start_line_no == end_line_no:
            line_info = "%d" % (start_line_no+1,)
        else:
            line_info = "%d:%d" % (start_line_no+1, end_line_no+1)
        print("  in %s at %s [%d:%d]" % (filename, line_info, start_char_no+1, end_char_no+1))
        # TODO: output the actual content of the lines the expression is from
        print("    ", end="")
        _f_write(expr)
        print()

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
def _operative_eq(env, expr, parent):
    _ERROR = "expected (eq? ANY ANY)"
    a, b = _unpack2(expr, _ERROR)
    if False:
        pass
    elif isinstance(a, Nil):
        result = TRUE if isinstance(b, Nil) else FALSE
    elif isinstance(a, Ignore):
        result = TRUE if isinstance(b, Ignore) else FALSE
    elif isinstance(a, Inert):
        result = TRUE if isinstance(b, Inert) else FALSE
    elif isinstance(a, Boolean):
        result = TRUE if isinstance(b, Boolean) and a.value == b.value else FALSE
    elif isinstance(a, Int):
        result = TRUE if isinstance(b, Int) and a.value == b.value else FALSE
    elif isinstance(a, Symbol):
        result = TRUE if isinstance(b, Symbol) and a.name == b.name else FALSE
    elif isinstance(a, String):
        result = TRUE if isinstance(b, String) and a.value == b.value else FALSE
    else:
        result = TRUE if a is b else FALSE
    return f_return(parent, result)

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

# ($vau (dyn args) expr)
def _operative_vau(env, expr, parent):
    _ERROR = "expected ($vau (PARAM PARAM) ANY)"
    envname_name, body = _unpack2(expr, _ERROR)
    envname, name = _unpack2(envname_name, _ERROR)
    if not isinstance(envname, Symbol) and not isinstance(envname, Ignore): raise RuntimeError(_ERROR)
    if not isinstance(name, Symbol) and not isinstance(name, Ignore): raise RuntimeError(_ERROR)
    immutable_body = _f_copy_immutable(body)
    return f_return(parent, Combiner(0, UserDefinedOperative(env, envname, name, immutable_body)))

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

# (eval env expr)
def _operative_eval(env, expr, parent):
    _ERROR = "expected (eval ENVIRONMENT ANY)"
    environment, expression = _unpack2(expr, _ERROR)
    if not isinstance(environment, Environment): raise RuntimeError(_ERROR)
    # Don't let the JIT driver promote the expression (since it can be a
    # mutable pair constructed at runtime)
    state = f_eval(environment, expression, parent)
    if jit.isvirtual(expression):
        state = step_evaluate(state)
    return state

# ($remote-eval env expr)
def _f_remote_eval(static, value, parent):
    assert isinstance(static, FRemoteEvalEnvironment)
    expression = static.expression
    if not isinstance(value, Environment):
        raise RuntimeError("expected environment argument value")
    if parent is not None:
        parent = Continuation(parent.env, parent.operative, parent.parent)
        parent._call_info = expression
    state = f_eval(value, expression, parent)
    if jit.isvirtual(expression):
        state = step_evaluate(state)
    return state
_F_REMOTE_EVAL = PrimitiveOperative(_f_remote_eval)
def _operative_remote_eval(env, expr, parent):
    _ERROR = "expected ($remote-eval ENVIRONMENT ANY)"
    environment, expression = _unpack2(expr, _ERROR)
    next_env = FRemoteEvalEnvironment(expression)
    next_continuation = Continuation(next_env, _F_REMOTE_EVAL, parent)
    next_continuation._call_info = environment
    state = f_eval(env, environment, next_continuation)
    if jit.isvirtual(environment):
        state = step_evaluate(state)
    return state

# (make-environment [parent])
def _operative_make_environment(env, expr, parent):
    _ERROR = "expected (make-environment [ENVIRONMENT])"
    if isinstance(expr, Nil):
        environment = None
    else:
        environment = _unpack1(expr, _ERROR)
        if not isinstance(environment, Environment): raise RuntimeError(_ERROR)
    return f_return(parent, Environment({}, environment))

# ($define! name value)
def _f_define(static, value, parent):
    assert isinstance(static, FDefineEnvironment)
    env = static.env
    assert isinstance(env, Environment)
    name = static.name
    assert isinstance(name, Symbol) or isinstance(name, Ignore)
    if isinstance(name, Symbol):
        _environment_update(env, name, value)
    return f_return(parent, INERT)
_F_DEFINE = PrimitiveOperative(_f_define)
def _operative_define(env, expr, parent):
    _ERROR = "expected ($define! PARAM ANY)"
    name, value = _unpack2(expr, _ERROR)
    if not isinstance(name, Symbol) and not isinstance(name, Ignore): raise RuntimeError(_ERROR)
    next_env = FDefineEnvironment(env, name)
    next_continuation = Continuation(next_env, _F_DEFINE, parent)
    next_continuation._call_info = value
    state = f_eval(env, value, next_continuation)
    if jit.isvirtual(value):
        state = step_evaluate(state)
    return state

# ($if cond then orelse)
def _f_if(static, result, parent):
    assert isinstance(static, FIfEnvironment)
    env = static.env
    if not isinstance(result, Boolean):
        raise RuntimeError("expected boolean test value")
    if result.value:
        then = static.then
        state = f_eval(env, then, parent)
        if jit.isvirtual(then):
            state = step_evaluate(state)
        return state
    else:
        orelse = static.orelse
        state = f_eval(env, orelse, parent)
        if jit.isvirtual(orelse):
            state = step_evaluate(state)
        return state
_F_IF = PrimitiveOperative(_f_if)
def _operative_if(env, expr, parent):
    _ERROR = "expected ($if ANY ANY ANY)"
    cond, then, orelse = _unpack3(expr, _ERROR)
    next_env = FIfEnvironment(env, then, orelse)
    next_continuation = Continuation(next_env, _F_IF, parent)
    next_continuation._call_info = cond
    state = f_eval(env, cond, next_continuation)
    if jit.isvirtual(cond):
        state = step_evaluate(state)
    return state

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
    state = f_eval(env, env_expr, next_continuation)
    if jit.isvirtual(env_expr):
        state = step_evaluate(state)
    return state

def _primitive(num_wraps, func):
    return Combiner(num_wraps, PrimitiveOperative(func))
_DEFAULT_ENV = {
    "+": _primitive(1, _operative_plus),
    "*": _primitive(1, _operative_times),
    "<=?": _primitive(1, _operative_less_equal),
    "eq?": _primitive(1, _operative_eq),
    "pair?": _primitive(1, _operative_pair),
    "cons": _primitive(1, _operative_cons),
    "car": _primitive(1, _operative_car),
    "cdr": _primitive(1, _operative_cdr),
    "$vau": _primitive(0, _operative_vau),
    "wrap": _primitive(1, _operative_wrap),
    "unwrap": _primitive(1, _operative_unwrap),
    "eval": _primitive(1, _operative_eval),
    "$remote-eval": _primitive(0, _operative_remote_eval),
    "make-environment": _primitive(1, _operative_make_environment),
    "$define!": _primitive(0, _operative_define),
    "$if": _primitive(0, _operative_if),
    "$binds?": _primitive(0, _operative_binds),
    "$jit-loop-head": Combiner(0, _F_LOOP_HEAD),
}

# == Entry point

def main(argv):
    import os
    # Configure JIT to allow larger traces
    jit.set_param(None, "trace_limit", 1000000)
    jit.set_param(None, "threshold", 131)
    jit.set_param(None, "trace_eagerness", 50)
    jit.set_param(None, "max_unroll_loops", 15)
    # Read whole STDIN
    parts = []
    while True:
        part = os.read(0, 2048)
        if not part: break
        parts.append(part)
    text = "".join(parts)
    # Lex and parse
    try:
        offsets = []
        tokens = tokenize(text, offsets=offsets)
        tokens.reverse()
        offsets.reverse()
        exprs = []
        locations = []
        while tokens:
            exprs.append(parse(tokens, offsets=offsets, locations=locations))
    except ParsingError as e:
        print("! --- syntax error ---")
        print("  in <stdin> at %d [%d:]" % (e.line_no + 1, e.char_no + 1))
        print("    ", end="")
        print(text.split("\n")[e.line_no])
        print("! syntax-error ", end="")
        _f_write(String(e.message))
        print()
        return 1
    # Setup standard environment
    env = Environment({}, Environment(_DEFAULT_ENV, None))
    # Evaluate expressions and write their results
    for expr in exprs:
        parent = Continuation(None, EVALUATION_DONE, None)
        parent._call_info = expr
        state = f_eval(env, expr, parent)
        try:
            value = fully_evaluate(state)
            if not isinstance(value, Inert):
                _f_write(value)
                print()
        except EvaluationError as e:
            if e.parent is not None:
                print("! --- stack trace ---")
                sources = {}
                for expr, l1, c1, l2, c2 in locations:
                    sources[expr] = ("<stdin>", l1, c1, l2, c2)
                _f_print_trace(e.parent, sources=sources)
            print("! error ", end="")
            _f_write(e.value)
            print()
            return 1
    return 0

# RPython toolchain
def target(driver, args):
    driver.exe_name = __name__
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
