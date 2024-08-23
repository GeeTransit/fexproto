($define! $car (unwrap car))
($define! $cdr (unwrap cdr))
($define! $cons (unwrap cons))
($define! get-current-environment (wrap ($vau (env _) env)))
($define! make-standard-environment (wrap ($vau (_1 _2) (get-current-environment))))
($define! list (wrap ($vau (_ args) args)))
($define! $sequence
	((wrap ($vau (_ $seq2)
			((car $seq2)
				($define! $aux-sequence ($vau (env exprs)
					($if (eq? (cdr exprs) ())
						(eval env (car exprs))
						((car $seq2)
							(eval env (car exprs))
							(eval env (cons $aux-sequence (cdr exprs)))))))
				($vau (env exprs)
					($if (eq? exprs ())
						#inert
						(eval env (cons $aux-sequence exprs)))))))
		((wrap ($vau (_ $basic-vau)
				((car $basic-vau) (env a-b)
					((wrap ((car $basic-vau) (_1 _2) (eval env (car (cdr a-b)))))
						(eval env (car a-b))))))
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
					#inert
					($if (pair? name)
						($sequence
							(eval env (list $aux-define! (car name) (car val)))
							(eval env (list $aux-define! (cdr name) (cdr val))))
						(eval env (list $basic-define! name (cons (unwrap list) val)))))))))
		($vau (env name-expr)
			(eval env (list
				$aux-define!
				(car name-expr)
				(eval env (car (cdr name-expr))))))))))
($define! $vau
	(($vau (_1 _2) ($sequence
		($define! $basic-vau $vau)
		($vau (static name-body)
			($basic-vau (dyn val)
				($sequence
					($define! env (make-environment static))
					(eval env (list $define! (car name-body) (list (unwrap list) dyn val)))
					(eval env (cons $sequence (cdr name-body))))))))))
($define! $lambda
	($vau (static name-body)
		(wrap (eval static
			(cons
				$vau
			(cons
				(list #ignore (car name-body))
				(cdr name-body)))))))
