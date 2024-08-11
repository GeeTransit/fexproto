def f_eval(env, expr):
    if type(expr) is str:
        return env[expr]
    elif type(expr) is tuple:
        return env[expr[0]](env, expr[1])

_DEFAULT_ENV = {
    "+": lambda env, expr: expr[0] + expr[1][0]
}

def main(env=_DEFAULT_ENV):
    import sys
    with open(sys.argv[1] if len(sys.argv) >= 2 else 0) as file:
        text = file.read()
    expr_stack = []
    for token in text.replace("(", " ( ").replace(")", " ) ").split():
        if token == "(":
            expr_stack.append(None)
        elif token == ")":
            if not expr_stack:
                exit(f'unmatched close bracket')
            rev_expr = expr_stack.pop()
            expr = None
            while rev_expr is not None:
                expr, rev_expr = (rev_expr[0], expr), rev_expr[1]
            if expr_stack:
                expr_stack[-1] = (expr, expr_stack[-1])
            else:
                print(f_eval(env, expr))
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
                print(f_eval(env, token))
    if expr_stack:
        exit(f'unclosed expression: {expr_stack}')

if __name__ == "__main__":
    main()
