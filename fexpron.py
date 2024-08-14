# wraps a function with zero, one, or more layers of argument evaluation
class Combiner:
    def __init__(self, num_wraps, func):
        assert num_wraps >= 0, f'expected non-negative wrap count, got {num_wraps}'
        self.num_wraps = num_wraps
        assert callable(func), f'combiner function is not callable: {func}'
        self.func = func

def f_eval(env, expr):
    if type(expr) is str:
        return env[expr]
    elif type(expr) is tuple:
        name, args = expr
        combiner = f_eval(env, name)
        for _ in range(combiner.num_wraps):
            args = _f_evlis(env, args)
        return combiner.func(env, args)
    elif type(expr) in (int, float, Combiner, bytes, type(...), bool):
        return expr
    else:
        exit(f'unknown expression type: {expr}')

# evaluate each element in the list
def _f_evlis(env, expr):
    rev_expr = None
    while expr is not None:
        rev_expr, expr = (f_eval(env, expr[0]), rev_expr), expr[1]
    while rev_expr is not None:
        expr, rev_expr = (rev_expr[0], expr), rev_expr[1]
    return expr

# load a file in an environment
def _f_load(env, expr):
    with open(expr.decode("utf-8")) as file:
        text = file.read()
    tokens = tokenize(text)
    try:
        exprs = parse(tokens)
    except ValueError as e:
        exit(e)
    for expr in exprs:
        f_eval(env, expr)

# modify environment according to name
def _f_define(env, name, expr, *, seen=None):
    if seen is None:
        seen = set()
    if type(name) is str:
        if name in seen:
            exit(f'match contains duplicate name: {name}')
        env[name] = expr
        seen.add(name)
    elif name is ...:
        pass
    elif name is None:
        if expr is not None:
            exit(f'expected nil match, got: {expr}')
    elif type(name) is tuple:
        if type(expr) is not tuple:
            exit(f'expected cons match on {name}, got: {expr}')
        _f_define(env, name[0], expr[0], seen=seen)
        _f_define(env, name[1], expr[1], seen=seen)
    else:
        exit(f'unknown match type: {name}')

def _f_vau(env, envname, name, body):
    def _f_call_vau(dyn, args):
        call_env = env.copy()
        _f_define(call_env, (envname, (name, None)), (dyn, (args, None)))
        return f_eval(call_env, body[0])
    return Combiner(0, _f_call_vau)

def _f_if(env, condition, on_true, on_false):
    result = f_eval(env, condition)
    if result is True:
        return f_eval(env, on_true)
    if result is False:
        return f_eval(env, on_false)
    exit(f'expected #t or #f as condition for $if, got: {result}')

_DEFAULT_ENV = {
    "+": Combiner(1, lambda env, expr: expr[0] + expr[1][0]),
    "$vau": Combiner(0, lambda env, expr: _f_vau(env, expr[0][0], expr[0][1][0], expr[1])),
    "eval": Combiner(1, lambda env, expr: f_eval(expr[0], expr[1][0])),
    "wrap": Combiner(1, lambda env, expr: Combiner(expr[0].num_wraps + 1, expr[0].func)),
    "unwrap": Combiner(1, lambda env, expr: Combiner(expr[0].num_wraps - 1, expr[0].func)),
    "$define!": Combiner(0, lambda env, expr: _f_define(env, expr[0], f_eval(env, expr[1][0]))),
    "$car": Combiner(0, lambda env, expr: expr[0][0]),
    "$cdr": Combiner(0, lambda env, expr: expr[0][1]),
    "load": Combiner(1, lambda env, expr: _f_load(env, expr[0])),
    "$if": Combiner(0, lambda env, expr: _f_if(env, expr[0], expr[1][0], expr[1][1][0])),
    "eq?": Combiner(1, lambda env, expr:
        expr[0] == expr[1][0]
        if type(expr[0]) is type(expr[1][0]) in (str, int, float, bytes)
        else expr[0] is expr[1][0]
    ),
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
        pprint.pp(f_eval(env, expr))

if __name__ == "__main__":
    main()
