from __future__ import print_function

# == Interpreter types and logic

class Object(object):
    pass
class Nil(Object):
    pass
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
    def __init__(self, num_wraps, func=None, operative=None):
        self.num_wraps = num_wraps
        self.func = func
        self.operative = operative
NIL = Nil()

class Operative(object):
    def __init__(self, env, envname, name, body):
        self.env = env
        self.envname = envname
        self.name = name
        self.body = body

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
        if combiner.func is None:
            assert combiner.operative is not None
            operative = combiner.operative
            call_env = Environment({
                operative.envname.name: env,
                operative.name.name: args,
            }, operative.env)
            return f_eval(call_env, operative.body)
        return combiner.func(env, args)
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
    return Combiner(0, operative=Operative(env, envname, name, body))

# (wrap combiner)
def _operative_wrap(env, expr):
    if (
        not isinstance(expr, Pair)
        or not isinstance(expr.cdr, Nil)
        or not isinstance(expr.car, Combiner)
    ):
        raise RuntimeError("expected (wrap COMBINER)")
    combiner = expr.car
    return Combiner(combiner.num_wraps + 1, combiner.func, combiner.operative)

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
    return Combiner(combiner.num_wraps - 1, combiner.func, combiner.operative)

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

_DEFAULT_ENV = {
    "+": Combiner(1, _operative_plus),
    "cons": Combiner(1, _operative_cons),
    "car": Combiner(1, _operative_car),
    "cdr": Combiner(1, _operative_cdr),
    "$vau": Combiner(0, _operative_vau),
    "wrap": Combiner(1, _operative_wrap),
    "unwrap": Combiner(1, _operative_unwrap),
    "$define!": Combiner(0, _operative_define),
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
