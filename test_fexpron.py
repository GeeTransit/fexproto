import fexpron as fx
tokens = fx.tokenize(r'''
(+ (+ 1 1) (+ 2 3))
(+ 1 4)
(($vau (e a) (+ (eval e (car a)) (eval e (car (cdr a))))) (+ 1 3) (+ 2 4))
''')
exprs = fx.parse(tokens)
for expr, expected in zip(exprs, [7, 5, 10]):
    actual = fx.f_eval(fx._DEFAULT_ENV, expr)
    assert actual == expected, f'{actual} != {expected} (expr={expr})'
