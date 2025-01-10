from __future__ import print_function

# == Interpreter types and logic

class Object(object):
    _attrs_ = _immutable_fields_ = ()
class Nil(Object):
    _attrs_ = _immutable_fields_ = ()
class Boolean(Object):
    _attrs_ = _immutable_fields_ = ("value",)
    def __init__(self, value):
        self.value = value
class Pair(Object):
    _attrs_ = ("car", "cdr")
    _immutable_fields_ = ()
    def __init__(self, car, cdr):
        self.car = car
        self.cdr = cdr
class Int(Object):
    _attrs_ = _immutable_fields_ = ("value",)
    def __init__(self, value):
        self.value = value
class Symbol(Object):
    _attrs_ = _immutable_fields_ = ("name",)
    def __init__(self, name):
        self.name = name
class Environment(Object):
    _attrs_ = _immutable_fields_ = ("bindings", "parent")
    def __init__(self, bindings, parent):
        assert parent is None or isinstance(parent, Environment)
        self.bindings = bindings
        self.parent = parent
class Continuation(Object):
    _attrs_ = _immutable_fields_ = ("env", "operative", "parent")
    def __init__(self, env, operative, parent):
        assert env is None or isinstance(env, Environment)
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
        self.env = env
        self.envname = envname
        self.name = name
        self.body = body
    def call(self, env, value, parent):
        call_env = Environment({
            self.envname.name: env,
            self.name.name: value,
        }, self.env)
        return f_eval(call_env, self.body, parent)

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

# Core interpreter logic

def f_return(parent, obj):
    return obj, None, parent
def f_eval(env, obj, parent=None):
    return obj, env, parent

def step_evaluate(state):
    obj, env, parent = state
    if env is None:
        return parent.operative.call(parent.env, obj, parent.parent)
    if isinstance(obj, Symbol):
        assert isinstance(env, Environment)
        while env is not None:
            if obj.name in env.bindings:
                return f_return(parent, env.bindings[obj.name])
            env = env.parent
        raise RuntimeError("binding not found", obj.name)
    elif isinstance(obj, Pair):
        next_env = StepWrappedEnvironment(env, obj.cdr)
        next_continuation = Continuation(next_env, _STEP_CALL_WRAPPED, parent)
        return f_eval(env, obj.car, next_continuation)
    else:
        return f_return(parent, obj)

def fully_evaluate(state):
    expr, env, continuation = state
    while continuation is not None or env is not None:
        expr, env, continuation = step_evaluate((expr, env, continuation))
    return expr

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

def tokenize(text):
    current = []
    result = []
    i = 0
    len_text = len(text)
    while True:
        if i == len_text or text[i] in " \t\r\n()":
            if current:
                result.append("".join(current))
                del current[:]
            if i != len_text and text[i] in "()":
                result.append(text[i:i+1])
        else:
            current.append(text[i])
        if i == len_text:
            return result
        i += 1

def parse(tokens):
    token = tokens.pop()
    if token == ")":
        raise RuntimeError("unmatched close bracket")
    if token == "(":
        return _parse_elements(tokens)
    if token == "#t" or token == "#T":
        return TRUE
    if token == "#f" or token == "#F":
        return FALSE
    try:
        return Int(int(token))
    except ValueError:
        return Symbol(token.lower())

def _parse_elements(tokens):
    token = tokens[-1]
    if token == ")":
        tokens.pop()
        return NIL
    if token == ".":
        tokens.pop()
        assert tokens[-1] != ")"
        element = parse(tokens)
        assert tokens.pop() == ")"
        return element
    element = parse(tokens)
    rest = _parse_elements(tokens)
    return Pair(element, rest)

def _f_write(obj):
    if isinstance(obj, Nil):
        print("()", end="")
    elif isinstance(obj, Int):
        print(str(obj.value), end="")
    elif isinstance(obj, Symbol):
        print(obj.name, end="")
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
    return f_return(parent, Pair(a, b))

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
    _ERROR = "expected ($vau (SYMBOL SYMBOL) ANY)"
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
    if not isinstance(envname, Symbol): raise RuntimeError(_ERROR)
    name = expr_car_cdr.car
    if not isinstance(name, Symbol): raise RuntimeError(_ERROR)
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
    assert isinstance(name, Symbol)
    env.bindings[name.name] = value
    return f_return(parent, NIL)
_F_DEFINE = PrimitiveOperative(_f_define)
def _operative_define(env, expr, parent):
    _ERROR = "expected ($define! SYMBOL ANY)"
    if not isinstance(expr, Pair): raise RuntimeError(_ERROR)
    expr_cdr = expr.cdr
    if not isinstance(expr_cdr, Pair): raise RuntimeError(_ERROR)
    if not isinstance(expr_cdr.cdr, Nil): raise RuntimeError(_ERROR)
    name = expr.car
    if not isinstance(name, Symbol): raise RuntimeError(_ERROR)
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
}

# == Entry point

def main(argv):
    import os
    # Read whole STDIN
    parts = []
    while True:
        part = os.read(0, 2048)
        if not part: break
        parts.append(part)
    text = "".join(parts)
    # Lex and parse
    tokens = tokenize(text)
    tokens.reverse()
    exprs = []
    while tokens:
        exprs.append(parse(tokens))
    # Setup standard environment
    env = Environment({}, Environment(_DEFAULT_ENV, None))
    # Evaluate expressions and write their results
    for expr in exprs:
        state = f_eval(env, expr)
        value = fully_evaluate(state)
        _f_write(value)
        print()
    return 0

# RPython toolchain
def target(driver, args):
    return main, None

# Python script
if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
