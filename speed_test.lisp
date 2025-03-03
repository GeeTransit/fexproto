($define! $sequence
	((wrap ($vau (#ignore $aux-seq)
			($vau (env exprs)
				($if (eq? exprs ()) #inert
					(eval env
						(cons (car $aux-seq)
						(cons (car $aux-seq)
							exprs)))))))
		((wrap ($vau (#ignore seq2-helper)
				($vau (env func-exprs)
					($if (eq? (cdr (cdr func-exprs)) ())
						(eval env (car (cdr func-exprs)))
						((car seq2-helper)
							env
							(car func-exprs)
							(cdr (cdr func-exprs))
							(eval env
								(cons $remote-eval
								(cons env
								(cons (car (cdr func-exprs))
									())))))))))
			(wrap ($vau (#ignore env-func-expr-temp)
				(eval (car env-func-expr-temp)
					(cons (car (cdr env-func-expr-temp))
					(cons (car (cdr env-func-expr-temp))
						(car (cdr (cdr env-func-expr-temp)))))))))))

($define! sumto (wrap ($vau (#ignore args)
	($sequence
		($jit-loop-head sumto)
		($if (eq? 0 (car args))
			(car (cdr args))
			(sumto (+ (car args) -1) (+ (car (cdr args)) (car args))))))))

; Various tests to illustrate relative speed
(sumto 10 0)
(sumto 100 0)
(sumto 1000 0)
(sumto 10000 0)
(sumto 100000 0)
(sumto 1000000 0)
(sumto 10000000 0)
(sumto 100000000 0)
(sumto 1000000000 0)
