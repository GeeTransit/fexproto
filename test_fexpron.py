import fexpron as fx
tokens = fx.tokenize(r'''
(+ (+ 1 1) (+ 2 3))
(+ 1 4)
(($vau (e (a b)) (+ (eval e a) (eval e b))) (+ 1 3) (+ 2 4))
((wrap (unwrap car)) (($vau (e a) a) a b c))
($define! std ($vau (#ignore name)
    (eval (make-standard-environment) (car name))))
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
        ($lambda (a)
                ($define! reverse-tail
                        ($lambda (in out)
                            ($if (eq? in ())
                                out
                                (reverse-tail (cdr in) (cons (car in) out)))))
                (reverse-tail a ())))
((unwrap reverse) (3 2 1))
((unwrap pair?) (1 2))
(call/cc ($lambda (cont) ((continuation->applicative cont) 1)))
(eq? #\a #\x61)
(<=? 1 2)
(call/cc ($lambda (cont)
    ((continuation->applicative
            (extend-continuation cont ($lambda (x) (+ x 1))))
        1)))
''')
exprs = fx.parse(tokens)
env = fx._make_standard_environment()
for expr, expected in zip(exprs, [7, 5, 10, "a", None, "a", None, "a", "c", 1, 0, True, True, True, fx.Pair(4, 6), None, fx.Pair(1, fx.Pair(2, fx.Pair(3, ()))), True, fx.Pair(1, ()), True, True, 2]):
    actual = fx.f_eval(env, expr)
    if expected is ...:
        continue
    assert actual == expected, f'{actual} != {expected} (expr={expr})'
