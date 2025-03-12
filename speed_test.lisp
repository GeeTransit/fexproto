; This is based on John Shutt's derivation of $sequence in [1] from primitive
; features. Modifications include the different parameters for $vau and $eval,
; the lack of recursive parameter tree binding, the lack of null? (which can be
; derived from eq?), the evaluation of expressions as arguments for better
; debug stack traces, a bug fix for late binding of $vau in $seq2, and a
; workaround to disable promotion of the recursive call expression.
;
; [1] J. N. Shutt, "Revised^-1 Report on the Kernel Programming Language",
;     Worcester Polytechnic Institute, Worcester, MA, Tech. Report.
;     WPI-CS-TR-05-07, Mar. 2005 [Amended 29 Oct. 2009]. [Online]. Available:
;     https://ftp.cs.wpi.edu/pub/techreports/pdf/05-07.pdf. [Accessed: 8 Mar.
;     2025]
($define! $sequence
	((wrap ($vau (#ignore list.)
			((wrap ($vau (#ignore $seq2.)
					((car $seq2.)
						($define! $aux
							($vau (env head.tail)
								($if (eq? () (cdr head.tail))
									(eval env (car head.tail))
									(eval env ((car list.) (car $seq2.)
										(car head.tail)
										(cons $aux (cdr head.tail)))))))
						($vau (env body)
							($if (eq? () body)
								#inert
								(eval env (cons $aux body)))))))
				((wrap ($vau (#ignore $vau.)
						($vau (env first.second.)
							(eval env ((car list.)
								(wrap ((car $vau.) (#ignore #ignore)
									(eval env (cons
										(car (car (cdr first.second.)))
										(cdr (car (cdr first.second.)))))))
								(car first.second.))))))
					$vau))))
		(wrap ($vau (#ignore args) args))))

; Simple tail recursive function where (sumto n 0) returns the sum of 1 to n
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
