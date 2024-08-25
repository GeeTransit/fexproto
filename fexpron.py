from functools import partial

# wraps a function with zero, one, or more layers of argument evaluation
class Combiner:
    def __init__(self, num_wraps, func):
        assert num_wraps >= 0, f'expected non-negative wrap count, got {num_wraps}'
        self.num_wraps = num_wraps
        assert callable(func), f'combiner function is not callable: {func}'
        self.func = func

class Environment:
    def __init__(self, bindings, parent):
        assert type(bindings) is dict, f'bindings must be dict, got: {type(bindings)}'
        self.bindings = bindings
        assert type(parent) is Environment, f'parent must type Environment, got: {type(parent)}'
        self.parent = parent
Environment.ROOT = object.__new__(Environment)

class Continuation:
    def __init__(self, env, expr, parent):
        assert type(env) is Environment, f'env must be type Environment, got: {type(env)}'
        self.env = env
        self.expr = expr
        assert type(parent) is Continuation, f'parent must be type Continuation, got: {type(parent)}'
        self.parent = parent
Continuation.ROOT = object.__new__(Continuation)

class Operative:
    def __init__(self, env, envname, name, body):
        assert type(env) is Environment, f'env must be type Environment, got: {type(env)}'
        self.env = env  # static environment (at time of declaration)
        assert type(envname) is str, f'envname must be type str, got: {type(envname)}'
        self.envname = envname  # name for dynamic environment
        assert type(name) is str, f'name must be type str, got: {type(name)}'
        self.name = name  # name for call arguments
        self.body = body  # function body
    def __call__(self, dyn, args, parent):
        # dyn is dynamic environment (at time of call)
        # args is call arguments
        # parent is parent continuation
        call_env = Environment({self.envname: dyn, self.name: args}, self.env)
        continuation = Continuation(call_env, self.body, parent)
        return continuation, None

def f_eval(env, expr):
    if type(env) is dict:
        env = Environment(env, Environment.ROOT)
    continuation, value = Continuation(env, expr, Continuation.ROOT), None
    while continuation is not Continuation.ROOT:
        continuation, value = step_evaluate(continuation, value)
        if continuation is Exception:
            raise ValueError(value)
    return value

# given a continuation and a value, get the next continuation and value
def step_evaluate(continuation, value):
    env = continuation.env
    expr = continuation.expr
    parent = continuation.parent
    if type(expr) is str:
        while env is not Environment.ROOT:
            if expr in env.bindings:
                return parent, env.bindings[expr]
            env = env.parent
        return Exception, f'binding not found: {expr}'
    elif type(expr) is tuple:
        if expr == ():
            return parent, expr
        name, args = expr
        # evaluate car of call
        continuation = Continuation(env, partial(_step_call_wrapped, args=args), parent)
        continuation = Continuation(env, name, continuation)
        return continuation, None
    elif type(expr) in (int, float, Combiner, bytes, type(...), bool, type(None), Continuation, Environment):
        return parent, expr
    elif callable(expr):
        return expr(env, value, parent=parent)
    else:
        return Exception, f'unknown expression type: {expr}'

# evaluate arguments based on num_wraps
def _step_call_wrapped(env, combiner, parent, args=()):
    continuation = Continuation(env, combiner.func, parent)
    continuation = Continuation(env, partial(_step_call_evlis, num_wraps=combiner.num_wraps), continuation)
    return continuation, args

# evaluate each element in the list
def _step_call_evlis(env, args, parent, num_wraps=1):
    if num_wraps > 0:
        continuation = Continuation(env, partial(_step_call_evlis, num_wraps=num_wraps - 1), parent)
        continuation = Continuation(env, partial(_step_call_evcar, pending=args), continuation)
        return continuation, None
    else:
        return parent, args

def _step_call_evcar(env, value, parent, pending=(), done=()):
    done = (value, done)
    if pending != ():
        # append the previous result and evaluate the next element
        continuation = Continuation(env, partial(_step_call_evcar, pending=pending[1], done=done), parent)
        continuation = Continuation(env, pending[0], continuation)
        return continuation, None
    else:
        args = ()
        while done != (): args, done = (done[0], args), done[1]
        return parent, args[1]

# load a file in an environment
def _f_load(env, expr, *, parent=None):
    with open(expr.decode("utf-8")) as file:
        text = file.read()
    tokens = tokenize(text)
    try:
        exprs = parse(tokens)
    except ValueError as e:
        return Exception, repr(e)
    args = ()
    for expr in reversed(exprs): args = expr, args
    continuation = Continuation(env, None, parent)
    continuation = Continuation(env, _step_call_evlis, continuation)
    return continuation, args

# modify environment according to name
def _f_define(static, expr, parent):
    env = static.bindings["env"]
    name = static.bindings["name"]
    env.bindings[name] = expr
    return parent, None

def _f_if(env, result, parent):
    if result is True:
        on_true = env.bindings["on_true"]
        env = env.bindings["env"]
        return Continuation(env, on_true, parent), None
    if result is False:
        on_false = env.bindings["on_false"]
        env = env.bindings["env"]
        return Continuation(env, on_false, parent), None
    return Exception, f'expected #t or #f as condition for $if, got: {result}'

def _f_abnormal_pass(env, _value, parent):
    return env.parent.bindings["continuation"], env.bindings["value"]

def _operative_plus(env, expr, parent):
    return parent, expr[0] + expr[1][0]

def _operative_vau(env, expr, parent):
    # ($vau (envname name) body)
    operative = Operative(env=env, envname=expr[0][0], name=expr[0][1][0], body=expr[1][0])
    return parent, Combiner(0, operative)

def _operative_eval(env, expr, parent):
    continuation = Continuation(expr[0], expr[1][0], parent)
    return continuation, None

def _operative_wrap(env, expr, parent):
    return parent, Combiner(expr[0].num_wraps + 1, expr[0].func)

def _operative_unwrap(env, expr, parent):
    return parent, Combiner(expr[0].num_wraps - 1, expr[0].func)

def _operative_define(env, expr, parent):
    next_env = Environment({"env": env, "name": expr[0]}, Environment.ROOT)
    continuation = Continuation(next_env, _f_define, parent)
    continuation = Continuation(env, expr[1][0], continuation)
    return continuation, None

def _operative_car(env, expr, parent):
    return parent, expr[0][0]

def _operative_cdr(env, expr, parent):
    return parent, expr[0][1]

def _operative_cons(env, expr, parent):
    return parent, (expr[0], expr[1][0])

def _operative_load(env, expr, parent):
    continuation = Continuation(env, _f_load, parent)
    return continuation, expr[0]

def _operative_if(env, expr, parent):
    next_env = Environment({"env": env, "on_true": expr[1][0], "on_false": expr[1][1][0]}, Environment.ROOT)
    continuation = Continuation(next_env, _f_if, parent)
    continuation = Continuation(env, expr[0], continuation)
    return continuation, None

def _operative_eq(env, expr, parent):
    return (parent,
        expr[0] == expr[1][0]
        if type(expr[0]) is type(expr[1][0]) in (str, int, float, bytes)
        else expr[0] is expr[1][0]
    )

def _operative_pair(env, expr, parent):
    return parent, type(expr[0]) is tuple and expr[0] != ()

def _operative_make_environment(_env, expr, parent):
    parent_env = expr[0] if expr != () else Environment.ROOT
    return parent, Environment({}, parent_env)

def _operative_continuation_to_applicative(_env, expr, parent):
    continuation = expr[0]
    if type(continuation) is not Continuation:
        return Exception, f'continuation must be type Continuation, got: {type(continuation)}'
    env = Environment({"continuation": continuation}, Environment.ROOT)
    operative = Operative(env, "_", "value", _f_abnormal_pass)
    return parent, Combiner(1, operative)

def _operative_call_cc(env, expr, parent):
    continuation = Continuation(env, (expr[0], (parent, ())), parent)
    return continuation, None

_DEFAULT_ENV = {
    "+": Combiner(1, _operative_plus),
    "$vau": Combiner(0, _operative_vau),
    "eval": Combiner(1, _operative_eval),
    "wrap": Combiner(1, _operative_wrap),
    "unwrap": Combiner(1, _operative_unwrap),
    "$define!": Combiner(0, _operative_define),
    "car": Combiner(1, _operative_car),
    "cdr": Combiner(1, _operative_cdr),
    "cons": Combiner(1, _operative_cons),
    "load": Combiner(1, _operative_load),
    "$if": Combiner(0, _operative_if),
    "eq?": Combiner(1, _operative_eq),
    "pair?": Combiner(1, _operative_pair),
    "make-environment": Combiner(1, _operative_make_environment),
    "continuation->applicative": Combiner(1, _operative_continuation_to_applicative),
    "call/cc": Combiner(1, _operative_call_cc),
}

def tokenize(text):
    return text.replace("(", " ( ").replace(")", " ) ").split()

def parse(tokens):
    exprs = []
    expr_stack = []
    for token in tokens:
        if token == "(":
            expr_stack.append(())
        elif token == ")":
            if not expr_stack:
                raise ValueError("unmatched close bracket")
            rev_expr = expr_stack.pop()
            expr = ()
            while rev_expr != ():
                expr, rev_expr = (rev_expr[0], expr), rev_expr[1]
            if expr_stack:
                expr_stack[-1] = (expr, expr_stack[-1])
            else:
                exprs.append(expr)
        else:
            if token[0] == '"' and token[-1] == '"' and len(token) >= 2:
                token = token[1:-1].encode("raw_unicode_escape").decode("unicode_escape").encode("utf-8")
            elif token == "#ignore":
                token = ...
            elif token == "#inert":
                token = None
            elif token in ("#t", "#f"):
                token = token == "#t"
            else:
                try:
                    token = float(token)
                except ValueError:
                    token = token.lower()
                else:
                    try:
                        token = int(token)
                    except ValueError:
                        token = token.lower()
            if expr_stack:
                expr_stack[-1] = (token, expr_stack[-1])
            else:
                exprs.append(token)
    if expr_stack:
        raise ValueError(f'unclosed expression: {expr_stack}')
    return exprs

# make a standard environment (should be constant)
def _make_standard_environment(*, primitives=None):
    if primitives is None:
        primitives = _DEFAULT_ENV

    # create standard environment with primitives as parent
    env = Environment(primitives, Environment.ROOT)
    env = Environment({}, env)

    # get standard library
    with open("std.lisp") as file:
        text = file.read()
    tokens = tokenize(text)
    exprs = parse(tokens)

    # evaluate in standard environment
    for expr in exprs:
        continuation, value = Continuation(env, expr, Continuation.ROOT), None
        while continuation is not Continuation.ROOT:
            continuation, value = step_evaluate(continuation, value)
            if continuation is Exception:
                raise ValueError(value)

    # return child of standard environment
    env = Environment({}, env)
    return env

def main(env=None):
    import pprint
    import sys
    with open(sys.argv[1] if len(sys.argv) >= 2 else 0) as file:
        text = file.read()
    tokens = tokenize(text)
    try:
        exprs = parse(tokens)
    except ValueError as e:
        exit(e)
    if env is None:
        env = _make_standard_environment()
    if type(env) is dict:
        env = Environment(env, Environment.ROOT)
    for expr in exprs:
        continuation, value = Continuation(env, expr, Continuation.ROOT), None
        while continuation is not Continuation.ROOT:
            continuation, value = step_evaluate(continuation, value)
            if continuation is Exception:
                exit(value)
        pprint.pp(value)

if __name__ == "__main__":
    main()
