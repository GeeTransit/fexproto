from __future__ import print_function

# Optional RPython imports
try:
    from rpython.rlib.rsre import rsre_re as re
    from rpython.rlib import jit
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
    _attrs_ = _immutable_fields_ = ("env", "operative", "parent")
    def __init__(self, env, operative, parent):
        assert env is None or isinstance(env, Environment)
        assert isinstance(operative, Operative)
        assert parent is None or isinstance(parent, Continuation)
        self.env = env
        self.operative = operative
        self.parent = parent
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
        return self.func(env, value, parent)
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

# Exceptions

class ParsingError(Exception):
    def __init__(self, message, line_no, char_no):
        self.message = message
        # Note that line_no and char_no must be on the exception instance since
        # unlike internal errors, there is no "source expression" to locate.
        self.line_no = line_no
        self.char_no = char_no

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
        raise RuntimeError("binding not found", name_name)
    if not jit.isvirtual(env) and not jit.isvirtual(env.localmap):
        jit.promote(env.localmap)
    index = env.localmap.find(name_name)
    if index >= 0:
        return env.storage[index]
    env = env.parent
    if env is None:
        raise RuntimeError("binding not found", name_name)
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
    raise RuntimeError("binding not found", name_name)

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
        return f_return(parent, _environment_lookup(env, obj))
    elif isinstance(obj, Pair):
        next_env = StepWrappedEnvironment(env, obj.cdr)
        next_continuation = Continuation(next_env, _STEP_CALL_WRAPPED, parent)
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
    while continuation is not None or (expr is not None and env is not None):
        jitdriver.jit_merge_point(expr=expr, env=env, continuation=continuation)
        expr, env, continuation = step_evaluate((expr, env, continuation))
        if continuation is not None and continuation.operative is _F_LOOP_CONSTANT:
            jitdriver.can_enter_jit(expr=expr, env=env, continuation=continuation)
    return env or expr

# TODO: Look into how Pycket does runtime call-graph construction to
# automatically infer loops. See https://doi.org/10.1145/2858949.2784740
def _f_loop_constant(env, expr, parent):
    return f_return(parent, INERT)
def _f_loop_head(env, expr, parent):
    next_continuation = Continuation(None, _F_LOOP_CONSTANT, parent)
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
    next_env = StepEvCarEnvironment(env, combiner.operative, combiner.num_wraps, args.cdr, p, 0, NIL)
    next_continuation = Continuation(next_env, _STEP_CALL_EVCAR, parent)
    return f_eval(env, args.car, next_continuation)
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
    next_continuation = Continuation(next_env, _STEP_CALL_EVCAR, parent)
    return f_eval(env, todo.car, next_continuation)
_STEP_CALL_EVCAR = PrimitiveOperative(_step_call_evcar)

# == Lexing, parsing, and writing logic

_TOKEN_PATTERN = re.compile("|".join([
    r'[()]',  # open and close brackets
    r'[^ \t\r\n();"]+',  # symbol-like tokens
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
    if token[0].isdigit() or token[0] in "+-" and len(token) > 1 and token[1].isdigit():
        return Int(int(token))
    if token[0] != "#":
        return Symbol(token.lower())
    raise ParsingError("unknown token", line_no, char_no)

def _parse_elements(
    tokens,
    offsets=None, locations=None,
    line_no=-1, char_no=-1,
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
    next_line_no = offsets[-1] if offsets is not None else -1
    next_char_no = offsets[-2] if offsets is not None else -1
    rest, end_line_no, end_char_no = _parse_elements(
        tokens,
        offsets=offsets, locations=locations,
        line_no=next_line_no, char_no=next_char_no,
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

# == Primitive combiners

# (+ a b)
def _operative_plus(env, expr, parent):
    _ERROR = "expected (+ INT INT)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    expr_cdr = expr.cdr
    if not isinstance(expr_cdr, Pair): raise RuntimeError(_ERROR)
    expr_cdr_cdr = expr_cdr.cdr
    if not isinstance(expr_cdr_cdr, Nil): raise RuntimeError(_ERROR)
    a = expr.car
    if not isinstance(a, Int): raise RuntimeError(_ERROR)
    b = expr_cdr.car
    if not isinstance(b, Int): raise RuntimeError(_ERROR)
    return f_return(parent, Int(a.value + b.value))

# (eq? a b)
def _operative_eq(env, expr, parent):
    _ERROR = "expected (eq? ANY ANY)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    expr_cdr = expr.cdr
    if not isinstance(expr_cdr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr_cdr.cdr, Nil): raise RuntimeError(_ERROR)
    a = expr.car
    b = expr_cdr.car
    if type(a) is not type(b):
        result = FALSE
    elif isinstance(a, Nil):
        result = TRUE
    elif isinstance(a, Ignore):
        result = TRUE
    elif isinstance(a, Inert):
        result = TRUE
    elif isinstance(a, Boolean):
        assert isinstance(b, Boolean)
        result = TRUE if a.value == b.value else FALSE
    elif isinstance(a, Int):
        assert isinstance(b, Int)
        result = TRUE if a.value == b.value else FALSE
    elif isinstance(a, Symbol):
        assert isinstance(b, Symbol)
        result = TRUE if a.name == b.name else FALSE
    else:
        result = TRUE if a is b else FALSE
    return f_return(parent, result)

# (pair? expr)
def _operative_pair(env, expr, parent):
    _ERROR = "expected (pair? ANY)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr.cdr, Nil): raise RuntimeError(_ERROR)
    pair = expr.car
    return f_return(parent, TRUE if isinstance(pair, Pair) else FALSE)

# (cons a b)
def _operative_cons(env, expr, parent):
    _ERROR = "expected (cons ANY ANY)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    expr_cdr = expr.cdr
    if not isinstance(expr_cdr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr_cdr.cdr, Nil): raise RuntimeError(_ERROR)
    a = expr.car
    b = expr_cdr.car
    return f_return(parent, MutablePair(a, b))

# (car pair)
def _operative_car(env, expr, parent):
    _ERROR = "expected (car PAIR)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr.cdr, Nil): raise RuntimeError(_ERROR)
    pair = expr.car
    if not isinstance(pair, Pair): raise RuntimeError(_ERROR)
    return f_return(parent, pair.car)

# (cdr pair)
def _operative_cdr(env, expr, parent):
    _ERROR = "expected (cdr PAIR)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr.cdr, Nil): raise RuntimeError(_ERROR)
    pair = expr.car
    if not isinstance(pair, Pair): raise RuntimeError(_ERROR)
    return f_return(parent, pair.cdr)

# ($vau (dyn args) expr)
def _operative_vau(env, expr, parent):
    _ERROR = "expected ($vau (PARAM PARAM) ANY)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    expr_cdr = expr.cdr
    if not isinstance(expr_cdr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr_cdr.cdr, Nil): raise RuntimeError(_ERROR)
    expr_car = expr.car
    if not isinstance(expr_car, Pair): raise RuntimeError(_ERROR)
    expr_car_cdr = expr_car.cdr
    if not isinstance(expr_car_cdr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr_car_cdr.cdr, Nil): raise RuntimeError(_ERROR)
    envname = expr_car.car
    if not isinstance(envname, Symbol) and not isinstance(envname, Ignore): raise RuntimeError(_ERROR)
    name = expr_car_cdr.car
    if not isinstance(name, Symbol) and not isinstance(name, Ignore): raise RuntimeError(_ERROR)
    body = expr_cdr.car
    return f_return(parent, Combiner(0, UserDefinedOperative(env, envname, name, body)))

# (wrap combiner)
def _operative_wrap(env, expr, parent):
    _ERROR = "expected (wrap COMBINER)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr.cdr, Nil): raise RuntimeError(_ERROR)
    combiner = expr.car
    if not isinstance(combiner, Combiner): raise RuntimeError(_ERROR)
    return f_return(parent, Combiner(combiner.num_wraps + 1, combiner.operative))

# (unwrap combiner)
def _operative_unwrap(env, expr, parent):
    _ERROR = "expected (unwrap COMBINER)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr.cdr, Nil): raise RuntimeError(_ERROR)
    combiner = expr.car
    if not isinstance(combiner, Combiner): raise RuntimeError(_ERROR)
    if combiner.num_wraps == 0: raise RuntimeError(_ERROR)
    return f_return(parent, Combiner(combiner.num_wraps - 1, combiner.operative))

# (eval env expr)
def _operative_eval(env, expr, parent):
    _ERROR = "expected (eval ENVIRONMENT ANY)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    expr_cdr = expr.cdr
    if not isinstance(expr_cdr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr_cdr.cdr, Nil): raise RuntimeError(_ERROR)
    environment = expr.car
    if not isinstance(environment, Environment): raise RuntimeError(_ERROR)
    expression = expr_cdr.car
    # Special-case operative calls to not let the JIT driver promote the pair
    if isinstance(expression, Pair):
        combiner = expression.car
        if isinstance(combiner, Combiner) and combiner.num_wraps == 0:
            return combiner.operative.call(environment, expression.cdr, parent)
    return f_eval(environment, expression, parent)

# (make-environment [parent])
def _operative_make_environment(env, expr, parent):
    _ERROR = "expected (make-environment [ENVIRONMENT])"
    if isinstance(expr, Nil):
        environment = None
    else:
        if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
        if not isinstance(expr.cdr, Nil): raise RuntimeError(_ERROR)
        environment = expr.car
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
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    expr_cdr = expr.cdr
    if not isinstance(expr_cdr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr_cdr.cdr, Nil): raise RuntimeError(_ERROR)
    name = expr.car
    if not isinstance(name, Symbol) and not isinstance(name, Ignore): raise RuntimeError(_ERROR)
    value = expr_cdr.car
    next_env = FDefineEnvironment(env, name)
    return f_eval(env, value, Continuation(next_env, _F_DEFINE, parent))

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
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    expr_cdr = expr.cdr
    if not isinstance(expr_cdr, Pair): raise RuntimeError(_ERROR)
    expr_cdr_cdr = expr_cdr.cdr
    if not isinstance(expr_cdr_cdr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr_cdr_cdr.cdr, Nil): raise RuntimeError(_ERROR)
    cond = expr.car
    then = expr_cdr.car
    orelse = expr_cdr_cdr.car
    next_env = FIfEnvironment(env, then, orelse)
    return f_eval(env, cond, Continuation(next_env, _F_IF, parent))

# ($binds? env name)
def _f_binds(static, value, parent):
    assert isinstance(static, FBindsEnvironment)
    name = static.name
    if not isinstance(value, Environment):
        raise RuntimeError("expected environment argument value")
    try:
        _environment_lookup(value, name)
    except RuntimeError:
        return f_return(parent, FALSE)
    return f_return(parent, TRUE)
_F_BINDS = PrimitiveOperative(_f_binds)
def _operative_binds(env, expr, parent):
    _ERROR = "expected ($binds? ENV SYMBOL)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    expr_cdr = expr.cdr
    if not isinstance(expr_cdr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr_cdr.cdr, Nil): raise RuntimeError(_ERROR)
    env_expr = expr.car
    name = expr_cdr.car
    if not isinstance(name, Symbol): raise RuntimeError(_ERROR)
    next_env = FBindsEnvironment(name)
    return f_eval(env, env_expr, Continuation(next_env, _F_BINDS, parent))

def _primitive(num_wraps, func):
    return Combiner(num_wraps, PrimitiveOperative(func))
_DEFAULT_ENV = {
    "+": _primitive(1, _operative_plus),
    "eq?": _primitive(1, _operative_eq),
    "pair?": _primitive(1, _operative_pair),
    "cons": _primitive(1, _operative_cons),
    "car": _primitive(1, _operative_car),
    "cdr": _primitive(1, _operative_cdr),
    "$vau": _primitive(0, _operative_vau),
    "wrap": _primitive(1, _operative_wrap),
    "unwrap": _primitive(1, _operative_unwrap),
    "eval": _primitive(1, _operative_eval),
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
        print('! syntax-error "%s"' % (e.message,))
        return 1
    # Setup standard environment
    env = Environment({}, Environment(_DEFAULT_ENV, None))
    # Evaluate expressions and write their results
    for expr in exprs:
        state = f_eval(env, expr)
        value = fully_evaluate(state)
        if not isinstance(value, Inert):
            _f_write(value)
            print()
    return 0

# RPython toolchain
def target(driver, args):
    return main, None
def jitpolicy(driver):
    from rpython.jit.codewriter.policy import JitPolicy
    return JitPolicy()

# Python script
if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
