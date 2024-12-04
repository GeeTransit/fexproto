($define! $car (unwrap car))
($define! $cdr (unwrap cdr))
($define! $cons (unwrap cons))
($define! list (wrap ($vau (_ args) args)))
($define! error
	((wrap ($vau (_ $basic-vau)
			(wrap ($vau (dyn error-args)
				(call/cc
					((car $basic-vau) (_ cc)
						(eval dyn
							(cons
								(unwrap (continuation->applicative error-continuation))
							(cons
								(car cc)
								error-args)))))))))
		$vau))
($define! $sequence
	((wrap ($vau (_ $seq2)
			((car $seq2)
				($define! $aux-sequence ($vau (env exprs)
					($if (eq? (cdr exprs) ())
						(eval env (car exprs))
						(eval env (list (car $seq2)
							(car exprs)
							(cons $aux-sequence (cdr exprs)))))))
				($vau (env exprs)
					($if (eq? exprs ())
						#inert
						(eval env (cons $aux-sequence exprs)))))))
		((wrap ($vau (_ $basic-vau)
				((car $basic-vau) (env a-b)
					(eval env (list
						(wrap ((car $basic-vau) (_1 _2)
							(eval env (car (cdr a-b)))))
						(car a-b))))))
			$vau)))
($define! $define!
	(($vau (_1 _2) ($sequence
		($define! $basic-define! $define!)
		($define! $aux-define! ($vau (env name-val) ($sequence
			($basic-define! name (car name-val))
			($basic-define! val (car (cdr name-val)))
			($if (eq? name #ignore)
				#inert
				($if (eq? name ())
					($if (eq? val ())
						#inert
						(error "expected\x20nil\x20match,\x20got:\x20" val))
					($if (pair? name)
						($if (pair? val)
							($sequence
								(eval env (list $aux-define! (car name) (car val)))
								(eval env (list $aux-define! (cdr name) (cdr val))))
							(error "expected\x20cons\x20match\x20on\x20" name ",\x20got\x20" val))
						(eval env (list $basic-define! name (cons (unwrap list) val)))))))))
		($vau (env name-expr)
			($if (eq? (cdr (cdr name-expr)) ())
				(eval env (list
					$aux-define!
					(car name-expr)
					(eval env (car (cdr name-expr)))))
				(error "expected\x20only\x20two\x20arguments")))))))
($define! $vau
	(($vau (_1 _2) ($sequence
		($define! $basic-vau $vau)
		($vau (static name-body)
			($sequence
				($define! name (copy-es-immutable (car name-body)))
				($define! body (copy-es-immutable (cdr name-body)))
				($basic-vau (dyn val)
					($sequence
						($define! env (make-environment static))
						(eval env (list $define! name (list (unwrap list) dyn val)))
						(eval env (cons $sequence body))))))))))
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
