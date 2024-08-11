import fexpron as fx
tokens = fx.tokenize(r'''
(+ (+ 1 1) (+ 2 3))
(+ 1 4)
($define! t-car (wrap $car))
($define! t-cdr (wrap $cdr))
(($vau (e a) (+ (eval e (t-car a)) (eval e (t-car (t-cdr a))))) (+ 1 3) (+ 2 4))
((wrap $car) (($vau (e a) a) a b c))
''')
exprs = fx.parse(tokens)
for expr, expected in zip(exprs, [7, 5, None, None, 10, "a"]):
    actual = fx.f_eval(fx._DEFAULT_ENV, expr)
    assert actual == expected, f'{actual} != {expected} (expr={expr})'
