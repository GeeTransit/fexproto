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
    elif type(expr) in (int, float, Combiner):
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
    with open(expr) as file:
        text = file.read()
    tokens = tokenize(text)
    try:
        exprs = parse(tokens)
    except ValueError as e:
        exit(e)
    for expr in exprs:
        f_eval(env, expr)
    return env

_DEFAULT_ENV = {
    "+": Combiner(1, lambda env, expr: expr[0] + expr[1][0]),
    "$vau": Combiner(0, lambda env, expr: Combiner(0, lambda dyn, args: f_eval({**env, expr[0][0]: dyn, expr[0][1][0]: args}, expr[1][0]))),
    "eval": Combiner(1, lambda env, expr: f_eval(expr[0], expr[1][0])),
    "wrap": Combiner(1, lambda env, expr: Combiner(expr[0].num_wraps + 1, expr[0].func)),
    "unwrap": Combiner(1, lambda env, expr: Combiner(expr[0].num_wraps - 1, expr[0].func)),
    "$define!": Combiner(0, lambda env, expr: env.__setitem__(expr[0], f_eval(env, expr[1][0]))),
    "$car": Combiner(0, lambda env, expr: expr[0][0]),
    "$cdr": Combiner(0, lambda env, expr: expr[0][1]),
    "load": Combiner(1, lambda env, expr: _f_load(expr[0], expr[1][0])),
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
            try:
                token = float(token)
            except ValueError:
                pass
            else:
                try:
                    token = int(token)
                except ValueError:
                    pass
            if expr_stack:
                expr_stack[-1] = (token, expr_stack[-1])
            else:
                exprs.append(token)
    if expr_stack:
        raise ValueError(f'unclosed expression: {expr_stack}')
    return exprs

def main(env=_DEFAULT_ENV):
    import sys
    with open(sys.argv[1] if len(sys.argv) >= 2 else 0) as file:
        text = file.read()
    tokens = tokenize(text)
    try:
        exprs = parse(tokens)
    except ValueError as e:
        exit(e)
    for expr in exprs:
        print(f_eval(env, expr))

if __name__ == "__main__":
    main()
