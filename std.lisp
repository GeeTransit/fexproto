($define! $car (unwrap car))
($define! $cdr (unwrap cdr))
($define! $cons (unwrap cons))
($define! list (wrap ($vau (#ignore args) args)))
($define! error
	((wrap ($vau (#ignore ($basic-vau))
			(wrap ($vau (dyn error-args)
				(call/cc
					($basic-vau (#ignore (cc))
						(eval dyn
							(cons
								(unwrap (continuation->applicative error-continuation))
							(cons
								cc
								error-args)))))))))
		$vau))

; This is based on John Shutt's derivation of $sequence in [1] from primitive
; features. Modifications include the different parameters for $vau and eval,
; the lack of null? (which can be derived from eq?), the evaluation of
; expressions as arguments for better debug stack traces, and a bug fix for
; late binding of $vau in $seq2.
;
; [1] J. N. Shutt, "Revised^-1 Report on the Kernel Programming Language",
;     Worcester Polytechnic Institute, Worcester, MA, Tech. Report.
;     WPI-CS-TR-05-07, Mar. 2005 [Amended 29 Oct. 2009]. [Online]. Available:
;     https://ftp.cs.wpi.edu/pub/techreports/pdf/05-07.pdf. [Accessed: 8 Mar.
;     2025]
($define! $sequence
	((wrap ($vau (#ignore ($seq2))
			($seq2
				($define! $aux-sequence ($vau (env (head . tail))
					($if (eq? tail ())
						(eval env head)
						(eval env (list $seq2
							head
							(cons $aux-sequence tail))))))
				($vau (env exprs)
					($if (eq? exprs ())
						#inert
						(eval env (cons $aux-sequence exprs)))))))
		((wrap ($vau (#ignore ($basic-vau))
				($vau (env (first second))
					(eval env (list
						(wrap ($basic-vau (#ignore #ignore)
							(eval env second)))
						first)))))
			$vau)))

($define! $vau
  ((wrap ($vau (#ignore ($basic-vau))
      ($vau (static (name . body))
        (eval static (list $basic-vau name (cons $sequence body))))))
    $vau))
($define! get-current-environment (wrap ($vau (env ()) env)))
($define! $lambda
	($vau (static (name . body))
		(wrap (eval static
			(cons
				$vau
			(cons
				(list #ignore name)
				body))))))
($define! make-standard-environment ($lambda () (get-current-environment)))
($define! null? ($lambda (item) (eq? () item)))
($define! $cond
	($vau (env ((cond . exprs) . rest))
		($if (eval env cond)
			(eval env (cons $sequence exprs))
			(eval env (cons $cond rest)))))
($define! not? ($lambda (bool) ($if bool #f #t)))
($define! $and? ($vau (env args)
	($cond
		((null? args) #t)
		((null? (cdr args)) (eval env (car args)))
		(#t
			(eval env (list $if (car args)
				(cons $and? (cdr args))
				#f))))))
($define! $or? ($vau (env args)
	($cond
		((null? args) #f)
		((null? (cdr args)) (eval env (car args)))
		(#t
			(eval env (list $if (car args)
				#t
				(cons $or? (cdr args))))))))
($define! apply
	($lambda (func args . env)
		(eval
			($cond
				((null? env) (make-environment))
				((null? (cdr env)) (car env))
				(#t (error "apply takes two or three arguments")))
			(cons (unwrap func) args))))
($define! list-tail
	($lambda (object offset)
		($cond
			((eq? offset 0)
				object)
			((<=? offset 0)
				(error "expected\x20non-negative\x20offset\x20to\x20list-tail"))
			(#t
				(list-tail (cdr object) (+ offset -1))))))
($define! $provide!
	($vau (env (symbols . body))
		(eval env
			(list $define! symbols
				(list
					(list $lambda ()
						(cons $sequence body)
						(cons list symbols)))))))
($provide! (get-list-metrics)
	($define! find-cycle
		($lambda (tortoise hare offset)
			($if (eq? tortoise hare)
				offset
				(find-cycle (cdr tortoise) (cdr hare) (+ 1 offset)))))
	($define! brent
		($lambda (tortoise hare hare-distance hare-power list-length obj)
			($cond
				((eq? #f (pair? hare))
					(list (+ list-length hare-distance) ($if (eq? hare ()) 1 0) (+ list-length hare-distance) 0))
				((eq? tortoise hare)
					($define! offset (find-cycle obj (list-tail obj hare-distance) 0))
					(list (+ offset hare-distance) 0 offset hare-distance))
				((eq? hare-distance hare-power)
					(brent hare (cdr hare) 1 (+ hare-power hare-power) (+ list-length hare-distance) obj))
				(#t
					(brent tortoise (cdr hare) (+ 1 hare-distance) hare-power list-length obj)))))
	($define! get-list-metrics
		($lambda (obj)
			($if (pair? obj)
				(brent obj (cdr obj) 1 1 0 obj)
				(list 0 ($if (eq? obj ()) 1 0) 0 0)))))
($define! assq
	($lambda (obj list)
		($if (null? list)
			()
			($if (eq? (car (car list)) obj)
				(car list)
				(assq obj (cdr list))))))
($define! append
	($lambda args
		($cond
			((null? args)
				())
			((null? (cdr args))
				(car args))
			((null? (car args))
				(apply append (cdr args)))
			((eq? #f (pair? (car args)))
				(error "expected\x20cons\x20cell,\x20got:\x20" (car args)))
			(#t
				(cons
					(car (car args))
					(apply append (cons
						(cdr (car args))
						(cdr args))))))))
($define! $binds?
	($vau (dyn (env-expr . names))
		($define! env (eval dyn env-expr))
		(call/cc ($lambda (cc)
			($define! inner
				(guard-continuation
					()
					cc
					(list
						(list
							error-continuation
							($lambda (#ignore divert)
								(apply divert #f))))))
			($define! check
				(extend-continuation inner
					($lambda ()
						(eval env (cons list names))
						#t)))
			((continuation->applicative check))))))
