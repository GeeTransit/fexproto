import fexpron as fx
tokens = fx.tokenize(r'''
(load "std.lisp")
(+ (+ 1 1) (+ 2 3))
(+ 1 4)
(($vau (e (a b)) (+ (eval e a) (eval e b))) (+ 1 3) (+ 2 4))
((wrap (unwrap car)) (($vau (e a) a) a b c))
($define! std
    (($vau (e a)
        ((wrap ($vau (e (#ignore std)) std))
            (load "std.lisp")
            ($vau (e (a)) (eval (($vau (e a) e)) a))))))
((std car) ($car ( (a b c) )))
($define! (temp1 (#ignore temp2)) ($car ((a (b c)))))
temp1
temp2
''')
exprs = fx.parse(tokens)
for expr, expected in zip(exprs, [..., 7, 5, 10, fx.Symbol("a"), ..., fx.Symbol("a"), None, fx.Symbol("a"), fx.Symbol("c")]):
    actual = fx.f_eval(fx._DEFAULT_ENV, expr)
    if expected is ...:
        continue
    assert actual == expected, f'{actual} != {expected} (expr={expr})'
