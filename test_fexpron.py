import fexpron as fx
tokens = fx.tokenize(r'''
(load "std.lisp")
(+ (+ 1 1) (+ 2 3))
(+ 1 4)
(($vau (e a) (+ (eval e (car a)) (eval e (car (cdr a))))) (+ 1 3) (+ 2 4))
((wrap (unwrap car)) (($vau (e a) a) a b c))
($define! std
    (($vau (e a)
        ((wrap ($vau (e a) (car (cdr a))))
            ($define! env (load "std.lisp"))
            ($vau (e a) (eval env (car a)))))))
((std car) ($car ( (a b c) )))
''')
exprs = fx.parse(tokens)
for expr, expected in zip(exprs, [..., 7, 5, 10, fx.Symbol("a"), ..., fx.Symbol("a")]):
    actual = fx.f_eval(fx._DEFAULT_ENV, expr)
    if expected is ...:
        continue
    assert actual == expected, f'{actual} != {expected} (expr={expr})'
