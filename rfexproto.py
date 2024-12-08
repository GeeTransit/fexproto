from __future__ import print_function

# == Interpreter types and logic

class Object(object):
    pass
class Nil(Object):
    pass
class Boolean(Object):
    def __init__(self, value):
        self.value = value
class Pair(Object):
    def __init__(self, car, cdr):
        self.car = car
        self.cdr = cdr
class Int(Object):
    def __init__(self, value):
        self.value = value
class Symbol(Object):
    def __init__(self, name):
        self.name = name
class Environment(Object):
    def __init__(self, bindings, parent):
        self.bindings = bindings
        self.parent = parent
class Combiner(Object):
    def __init__(self, num_wraps, operative):
        self.num_wraps = num_wraps
        self.operative = operative
NIL = Nil()
TRUE = Boolean(True)
FALSE = Boolean(False)

class Operative(object):
    def call(self, env, value): assert False
class PrimitiveOperative(Operative):
    def __init__(self, func):
        self.func = func
    def call(self, env, value):
        return self.func(env, value)
class UserDefinedOperative(Operative):
    def __init__(self, env, envname, name, body):
        self.env = env
        self.envname = envname
        self.name = name
        self.body = body
    def call(self, env, value):
        call_env = Environment({
            self.envname.name: env,
            self.name.name: value,
        }, self.env)
        return f_eval(call_env, self.body)

def f_eval(env, obj):
    if isinstance(obj, Symbol):
        while env is not None:
            if obj.name in env.bindings:
                return env.bindings[obj.name]
            env = env.parent
        raise RuntimeError("binding not found")
    elif isinstance(obj, Pair):
        combiner = f_eval(env, obj.car)
        args = obj.cdr
        if not isinstance(combiner, Combiner):
            raise RuntimeError("call car must be a combiner")
        if combiner.num_wraps > 0:
            c = args; p = 0
            while isinstance(c, Pair): p += 1; c = c.cdr
            if not isinstance(c, Nil):
                raise RuntimeError("applicative call args must be proper list")
            c = args; r = s = Pair(NIL, NIL)
            for _ in range(p): s.cdr = s = Pair(c.car, NIL); c = c.cdr
            for _ in range(combiner.num_wraps):
                s = r.cdr
                for _ in range(p): s.car = f_eval(env, s.car); s = s.cdr
            args = r.cdr
        return combiner.operative.call(env, args)
    else:
        return obj

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
        return NIL
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
        while isinstance(obj.cdr, Pair):
            obj = obj.cdr
            print(" ", end="")
            _f_write(obj.car)
        if not isinstance(obj.cdr, Nil):
            print(" . ", end="")
            _f_write(obj.cdr)
        print(")", end="")
    else:
        print("#unknown", end="")

# == Primitive combiners

# (+ a b)
def _operative_plus(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Pair)
        or not isinstance(expr.cdr.cdr, Nil)
        or not isinstance(expr.car, Int)
        or not isinstance(expr.cdr.car, Int)
    ):
        raise RuntimeError("expected (+ INT INT)")
    a = expr.car
    b = expr.cdr.car
    return Int(a.value + b.value)

# (eq? a b)
def _operative_eq(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Pair)
        or not isinstance(expr.cdr.cdr, Nil)
    ):
        raise RuntimeError("expected (eq? ANY ANY)")
    a = expr.car
    b = expr.cdr.car
    if type(a) is not type(b):
        return FALSE
    if isinstance(a, Nil):
        return TRUE
    if isinstance(a, Boolean):
        return TRUE if a.value == b.value else FALSE
    if isinstance(a, Int):
        return TRUE if a.value == b.value else FALSE
    if isinstance(a, Symbol):
        return TRUE if a.name == b.name else FALSE
    return TRUE if a is b else FALSE

# (pair? expr)
def _operative_pair(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Nil)
    ):
        raise RuntimeError("expected (pair? ANY)")
    pair = expr.car
    return TRUE if isinstance(pair, Pair) else FALSE

# (cons a b)
def _operative_cons(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Pair)
        or not isinstance(expr.cdr.cdr, Nil)
    ):
        raise RuntimeError("expected (cons ANY ANY)")
    a = expr.car
    b = expr.cdr.car
    return Pair(a, b)

# (car pair)
def _operative_car(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Nil)
        or not isinstance(expr.car, Pair)
    ):
        raise RuntimeError("expected (car PAIR)")
    pair = expr.car
    return pair.car

# (cdr pair)
def _operative_cdr(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Nil)
        or not isinstance(expr.car, Pair)
    ):
        raise RuntimeError("expected (cdr PAIR)")
    pair = expr.car
    return pair.cdr

# ($vau (dyn args) expr)
def _operative_vau(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Pair)
        or not isinstance(expr.cdr.cdr, Nil)
        or not isinstance(expr.car, Pair)
        or not isinstance(expr.car.cdr, Pair)
        or not isinstance(expr.car.cdr.cdr, Nil)
        or not isinstance(expr.car.car, Symbol)
        or not isinstance(expr.car.cdr.car, Symbol)
    ):
        raise RuntimeError("expected ($vau (SYMBOL SYMBOL) ANY)")
    envname = expr.car.car
    name = expr.car.cdr.car
    body = expr.cdr.car
    return Combiner(0, UserDefinedOperative(env, envname, name, body))

# (wrap combiner)
def _operative_wrap(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Nil)
        or not isinstance(expr.car, Combiner)
    ):
        raise RuntimeError("expected (wrap COMBINER)")
    combiner = expr.car
    return Combiner(combiner.num_wraps + 1, combiner.operative)

# (unwrap combiner)
def _operative_unwrap(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Nil)
        or not isinstance(expr.car, Combiner)
        or expr.car.num_wraps == 0
    ):
        raise RuntimeError("expected (unwrap COMBINER)")
    combiner = expr.car
    return Combiner(combiner.num_wraps - 1, combiner.operative)

# (eval env expr)
def _operative_eval(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Pair)
        or not isinstance(expr.cdr.cdr, Nil)
        or not isinstance(expr.car, Environment)
    ):
        raise RuntimeError("expected (eval ENVIRONMENT ANY)")
    environment = expr.car
    expression = expr.cdr.car
    return f_eval(environment, expression)

# (make-environment [parent])
def _operative_make_environment(env, expr):
    if (
        not isinstance(expr, Nil)
        and not (
            isinstance(expr, Pair)
            and isinstance(expr.cdr, Nil)
            and isinstance(expr.car, Environment)
        )
    ):
        raise RuntimeError("expected (make-environment [ENVIRONMENT])")
    if isinstance(expr, Nil):
        environment = None
    else:
        environment = expr.car
    return Environment({}, environment)

# ($define! name value)
def _operative_define(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Pair)
        or not isinstance(expr.cdr.cdr, Nil)
        or not isinstance(expr.car, Symbol)
    ):
        raise RuntimeError("expected ($define! SYMBOL ANY)")
    name = expr.car
    value = expr.cdr.car
    env.bindings[name.name] = f_eval(env, value)
    return NIL

# ($if cond then orelse)
def _operative_if(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Pair)
        or not isinstance(expr.cdr.cdr, Pair)
        or not isinstance(expr.cdr.cdr.cdr, Nil)
    ):
        raise RuntimeError("expected ($if ANY ANY ANY)")
    cond = expr.car
    then = expr.cdr.car
    orelse = expr.cdr.cdr.car
    result = f_eval(env, cond)
    if not isinstance(result, Boolean):
        raise RuntimeError("expected boolean test value")
    if result.value:
        return f_eval(env, then)
    else:
        return f_eval(env, orelse)

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
        _f_write(f_eval(env, expr))
        print()
    return 0

# RPython toolchain
def target(driver, args):
    return main, None

# Python script
if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
