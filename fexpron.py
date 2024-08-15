from functools import partial

# wraps a function with zero, one, or more layers of argument evaluation
class Combiner:
    def __init__(self, num_wraps, func):
        assert num_wraps >= 0, f'expected non-negative wrap count, got {num_wraps}'
        self.num_wraps = num_wraps
        assert callable(func), f'combiner function is not callable: {func}'
        self.func = func

class Continuation:
    def __init__(self, env, expr, parent):
        assert type(env) is dict, f'env must be type dict, got: {type(env)}'
        self.env = env
        self.expr = expr
        assert parent is None or type(parent) is Continuation, f'parent must be None or type Continuation, got: {type(parent)}'
        self.parent = parent

def f_eval(env, expr):
    continuation, value = Continuation(env, expr, None), None
    while True:
        continuation, value = step_evaluate(continuation, value)
        if continuation is Exception:
            raise ValueError(value)
        if continuation is None:
            return value

# given a continuation and a value, get the next continuation and value
def step_evaluate(continuation, value):
    env = continuation.env
    expr = continuation.expr
    parent = continuation.parent
    if type(expr) is str:
        return parent, env[expr]
    elif type(expr) is tuple:
        name, args = expr
        # evaluate car of call
        continuation = Continuation(env, partial(_step_call_wrapped, args=args), parent)
        continuation = Continuation(env, name, continuation)
        return continuation, None
    elif type(expr) in (int, float, Combiner, bytes, type(...), bool, type(None)):
        return parent, expr
    elif callable(expr):
        return expr(env, value, parent=parent)
    else:
        return Exception, f'unknown expression type: {expr}'

# evaluate arguments based on num_wraps
def _step_call_wrapped(env, combiner, parent, args=None):
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

def _step_call_evcar(env, value, parent, pending=None, done=None):
    done = (value, done)
    if pending is not None:
        # append the previous result and evaluate the next element
        continuation = Continuation(env, partial(_step_call_evcar, pending=pending[1], done=done), parent)
        continuation = Continuation(env, pending[0], continuation)
        return continuation, None
    else:
        args = None
        while done is not None: args, done = (done[0], args), done[1]
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
    args = None
    for expr in reversed(exprs): args = expr, args
    continuation = Continuation(env, None, parent)
    continuation = Continuation(env, _step_call_evlis, continuation)
    return continuation, args

# modify environment according to name
def _f_define(env, expr, name, *, seen=None, parent=None, _sendval=None):
    if seen is None:
        seen = set()
    if type(name) is str:
        if name in seen:
            return Exception, f'match contains duplicate name: {name}'
        env[name] = expr
        seen.add(name)
    elif name is ...:
        pass
    elif name is None:
        if expr is not None:
            return Exception, f'expected nil match, got: {expr}'
    elif type(name) is tuple:
        if type(expr) is not tuple:
            return Exception, f'expected cons match on {name}, got: {expr}'
        continuation = Continuation(env, partial(_f_define, name=name[1], seen=seen, _sendval=_sendval), parent)
        continuation = Continuation(env, partial(_f_define, name=name[0], seen=seen, _sendval=expr[1]), continuation)
        return continuation, expr[0]
    else:
        return Exception, f'unknown match type: {name}'
    return parent, _sendval

def _f_vau(env, envname, name, body):
    def _f_call_vau(dyn, args, parent):
        call_env = env.copy()
        continuation = Continuation(call_env, body[0], parent)
        continuation = Continuation(call_env, partial(_f_define, name=(envname, (name, None))), continuation)
        return continuation, (dyn, (args, None))
    return Combiner(0, _f_call_vau)

def _f_if(env, result, on_true, on_false, *, parent=None):
    if result is True:
        return Continuation(env, on_true, parent), None
    if result is False:
        return Continuation(env, on_false, parent), None
    return Exception, f'expected #t or #f as condition for $if, got: {result}'

_DEFAULT_ENV = {
    "+": Combiner(1, lambda env, expr, parent: (parent, expr[0] + expr[1][0])),
    "$vau": Combiner(0, lambda env, expr, parent: (parent, _f_vau(env, expr[0][0], expr[0][1][0], expr[1]))),
    "eval": Combiner(1, lambda env, expr, parent: (Continuation(expr[0], expr[1][0], parent), None)),
    "wrap": Combiner(1, lambda env, expr, parent: (parent, Combiner(expr[0].num_wraps + 1, expr[0].func))),
    "unwrap": Combiner(1, lambda env, expr, parent: (parent, Combiner(expr[0].num_wraps - 1, expr[0].func))),
    "$define!": Combiner(0, lambda env, expr, parent: (Continuation(env, expr[1][0], Continuation(env, partial(_f_define, name=expr[0]), parent)), None)),
    "car": Combiner(1, lambda env, expr, parent: (parent, expr[0][0])),
    "cdr": Combiner(1, lambda env, expr, parent: (parent, expr[0][1])),
    "load": Combiner(1, lambda env, expr, parent: (Continuation(env, _f_load, parent), expr[0])),
    "$if": Combiner(0, lambda env, expr, parent: (Continuation(env, expr[0], Continuation(env, partial(_f_if, on_true=expr[1][0], on_false=expr[1][1][0]), parent)), None)),
    "eq?": Combiner(1, lambda env, expr, parent: (parent,
        expr[0] == expr[1][0]
        if type(expr[0]) is type(expr[1][0]) in (str, int, float, bytes)
        else expr[0] is expr[1][0]
    )),
}

def tokenize(text):
    return text.replace("(", " ( ").replace(")", " ) ").split()

def parse(tokens):
    exprs = []
    expr_stack = []
    for token in tokens:
        if token == "(":
            expr_stack.append(None)
        elif token == ")":
            if not expr_stack:
                raise ValueError("unmatched close bracket")
            rev_expr = expr_stack.pop()
            expr = None
            while rev_expr is not None:
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

def main(env=_DEFAULT_ENV):
    import pprint
    import sys
    with open(sys.argv[1] if len(sys.argv) >= 2 else 0) as file:
        text = file.read()
    tokens = tokenize(text)
    try:
        exprs = parse(tokens)
    except ValueError as e:
        exit(e)
    for expr in exprs:
        continuation, value = Continuation(env, expr, None), None
        while True:
            continuation, value = step_evaluate(continuation, value)
            if continuation is Exception:
                exit(value)
            if continuation is None:
                break
        pprint.pp(value)

if __name__ == "__main__":
    main()
