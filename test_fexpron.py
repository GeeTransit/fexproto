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
((std $car) (a b c))
($define! (temp1 (#ignore temp2)) ($car ((a (b c)))))
temp1
temp2
($if (eq? ($car (a)) ($car (a))) 1 0)
($if (eq? #f (eq? #ignore #ignore)) 1 0)
(eq? 3 (+ 1 2))
(eq? 3.5 (+ 3 0.5))
(eq? "hi" "hi")
(cons 4 6)
($define! reverse
    (wrap
        ($vau (e (a))
            ((wrap ($vau (e (a b)) b))
                ($define! reverse-tail
                    (wrap
                        ($vau (e (in out))
                            ($if (eq? in ())
                                out
                                (reverse-tail (cdr in) (cons (car in) out))))))
                (reverse-tail a ())))))
((unwrap reverse) (3 2 1))
''')
exprs = fx.parse(tokens)
env = fx._DEFAULT_ENV.copy()
for expr, expected in zip(exprs, [None, 7, 5, 10, "a", ..., "a", None, "a", "c", 1, 0, True, True, True, (4, 6), None, (1, (2, (3, None)))]):
    actual = fx.f_eval(env, expr)
    if expected is ...:
        continue
    assert actual == expected, f'{actual} != {expected} (expr={expr})'
