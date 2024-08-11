def f_eval(env, expr):
    if type(expr) is str:
        return env[expr]
    elif type(expr) is tuple:
        return f_eval(env, expr[0])(env, expr[1])
    elif type(expr) in (int, float):
        return expr
    else:
        exit(f'unknown expression type: {expr}')

_DEFAULT_ENV = {
    "+": lambda env, expr: f_eval(env, expr[0]) + f_eval(env, expr[1][0]),
    "$vau": lambda env, expr: lambda dyn, args: f_eval({**env, expr[0][0]: dyn, expr[0][1][0]: args}, expr[1][0]),
    "car": lambda env, expr: f_eval(env, expr[0])[0],
    "cdr": lambda env, expr: f_eval(env, expr[0])[1],
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
