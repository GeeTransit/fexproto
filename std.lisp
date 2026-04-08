;
; Copyright (C) 2024-2026 George Zhang
;
; This program is free software: you can redistribute it and/or modify
; it under the terms of the GNU General Public License as published by
; the Free Software Foundation, either version 3 of the License, or
; (at your option) any later version.
;
; This program is distributed in the hope that it will be useful,
; but WITHOUT ANY WARRANTY; without even the implied warranty of
; MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
; GNU General Public License for more details.
;
; You should have received a copy of the GNU General Public License
; along with this program.  If not, see <https://www.gnu.org/licenses/>.
;

($define! $car (unwrap car))
($define! $cdr (unwrap cdr))
($define! $cons (unwrap cons))
($define! car (wrap ($vau (#ignore ((x . #ignore))) x)))
($define! cdr (wrap ($vau (#ignore ((#ignore . x))) x)))
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
($if ($binds? (($vau (env #ignore) env)) error-continuation)
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
  ($define! error
      (wrap ($vau (dyn error-args)
        (eval (make-environment) (list (cons ((unwrap list) . error) error-args)))))))

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

($if ($binds? (($vau (env #ignore) env)) copy-es-immutable) #inert
  ($define! copy-es-immutable
    ((wrap ($vau (#ignore ($basic-vau))
        (wrap ($vau (#ignore expr)
          (((wrap $basic-vau) (list #ignore #ignore)
            (cons (unwrap list) (car expr))))))))
      $vau)))
($define! $vau
  ((wrap ($vau (#ignore ($basic-vau))
      ($vau (static ((envname name) . body))
        (eval static (list $basic-vau (list envname name) (cons $sequence body))))))
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

; type predicates that could be derived using eq?
($if ($binds? (get-current-environment) boolean?) #inert
  ($define! boolean? ($lambda (item) ($if (eq? obj #t) #t (eq? obj #f)))))
($if ($binds? (get-current-environment) null?) #inert
  ($define! null? ($lambda (item) (eq? () item))))
($if ($binds? (get-current-environment) inert?) #inert
  ($define! inert? ($lambda (item) (eq? item #inert))))
($if ($binds? (get-current-environment) ignore?) #inert
  ($define! ignore? ($lambda (item) (eq? item #ignore))))

; TODO: support cyclic args
($define! map
  (wrap ($vau (static (func args))
    ($if (eq? () args) ()
      (cons
        (eval static (cons (unwrap func) (cons (car args) ())))
        (map func (cdr args)))))))
($define! $let
  ($vau (static (bindings . body))
    (eval static
      (cons
        (cons $lambda (cons (map car bindings) body))
        (map car (map cdr bindings))))))
($define! $cond
	($vau (dyn args)
		($if (eq? () args) #inert
      ($sequence
        ($define! ((cond . then) . rest) args)
        (eval dyn (list $if cond
          (cons $sequence then)
          (cons $cond rest)))))))
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

($provide! (list*)
  ($define! naive-list* ($lambda ((obj . rest))
    ($if (null? rest) obj
      (cons obj (naive-list* rest)))))
  ($define! list* ($lambda objs
    ($define! (p n #ignore #ignore) (get-list-metrics objs))
    ($if ($or? (eq? p 0) (eq? n 0))
      (error "list* accepts finite and non-zero arguments")
      (naive-list* objs)))))

; TODO: generate these automatically
($define! caar ($lambda (x) (car (car x))))
($define! cadr ($lambda (x) (car (cdr x))))
($define! cdar ($lambda (x) (cdr (car x))))
($define! cddr ($lambda (x) (cdr (cdr x))))

($define! caaar ($lambda (x) (car (car (car x)))))
($define! caadr ($lambda (x) (car (car (cdr x)))))
($define! cadar ($lambda (x) (car (cdr (car x)))))
($define! caddr ($lambda (x) (car (cdr (cdr x)))))
($define! cdaar ($lambda (x) (cdr (car (car x)))))
($define! cdadr ($lambda (x) (cdr (car (cdr x)))))
($define! cddar ($lambda (x) (cdr (cdr (car x)))))
($define! cdddr ($lambda (x) (cdr (cdr (cdr x)))))

($define! caaaar ($lambda (x) (car (car (car (car x))))))
($define! caaadr ($lambda (x) (car (car (car (cdr x))))))
($define! caadar ($lambda (x) (car (car (cdr (car x))))))
($define! caaddr ($lambda (x) (car (car (cdr (cdr x))))))
($define! cadaar ($lambda (x) (car (cdr (car (car x))))))
($define! cadadr ($lambda (x) (car (cdr (car (cdr x))))))
($define! caddar ($lambda (x) (car (cdr (cdr (car x))))))
($define! cadddr ($lambda (x) (car (cdr (cdr (cdr x))))))
($define! cdaaar ($lambda (x) (cdr (car (car (car x))))))
($define! cdaadr ($lambda (x) (cdr (car (car (cdr x))))))
($define! cdadar ($lambda (x) (cdr (car (cdr (car x))))))
($define! cdaddr ($lambda (x) (cdr (car (cdr (cdr x))))))
($define! cddaar ($lambda (x) (cdr (cdr (car (car x))))))
($define! cddadr ($lambda (x) (cdr (cdr (car (cdr x))))))
($define! cdddar ($lambda (x) (cdr (cdr (cdr (car x))))))
($define! cddddr ($lambda (x) (cdr (cdr (cdr (cdr x))))))

($define! encycle! ($lambda (ls a c)
  ($if (<=? c 0) #inert
    (set-cdr! (list-tail ls (+ a (+ c -1)))
              (list-tail ls a)))))

($provide! (and?)
  ($define! and-helper
    ($lambda (bools k)
      ($cond
        ((<=? k 0) #t)
        ((car bools) (and-helper (cdr bools) (+ k -1)))
        (#t #f))))
  ($define! and?
    ($lambda bools
      ($define! (p #ignore #ignore #ignore) (get-list-metrics bools))
      (and-helper bools p))))

($provide! (or?)
  ($define! or-helper
    ($lambda (bools k)
      ($cond
        ((<=? k 0) #f)
        ((car bools) #t)
        (#t (or-helper (cdr bools) (+ k -1))))))
  ($define! or?
    ($lambda bools
      ($define! (p #ignore #ignore #ignore) (get-list-metrics bools))
      (or-helper bools p))))

($define! combiner? ($lambda (obj)
  ($or? (operative? obj) (applicative? obj))))

; TODO: uncomment when infinities are supported
; ($define! length ($lambda (obj)
  ; ($define! (#ignore #ignore a c) (get-list-metrics obj))
  ; ($if (<=? c 0) a #e+infinity)))

($define! list-ref ($lambda (ls k) (car (list-tail ls k))))

; TODO: error on cyclic arg and support cyclic args
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
				(error "append arguments must be acyclic lists, not including last argument"))
			(#t
				(cons
					(car (car args))
					(apply append (cons
						(cdr (car args))
						(cdr args))))))))

($provide! (list-neighbors)
  ; rf> (list-neighbors ((unwrap list) . (1 2 3 . #up<3>)))
  ; ((1 2) (2 3) (3 1) . #up<3>)
  ($define! neighbors-helper ($lambda (ls k)
    ($if (<=? k 0) ()
      (cons (list (car ls) (cadr ls))
            (neighbors-helper (cdr ls) (+ k -1))))))
  ($define! list-neighbors ($lambda (ls)
    ($define! (p #ignore a c) (get-list-metrics ls))
    ($cond
      ((<=? c 0) (neighbors-helper ls (+ a -1)))
      (#t
        ($define! res (neighbors-helper ls p))
        (encycle! res a c)
        res)))))

($if ($binds? (get-current-environment) extend-continuation)
  ($provide! (extend-continuation)
    ($define! old-extend-continuation extend-continuation)
    ($define! extend-continuation ($lambda (cont func . env)
      ($if (eq? env ())
           ($define! env (make-environment))
           ($define! (env) env))
      ($define! func (unwrap func))
      ($define! appl (wrap ($vau (env value) (eval env (cons func value)))))
      (old-extend-continuation cont appl env))))
  #inert)

($if ($binds? (get-current-environment) read-file)
  ($provide! (load)
    ($define! load ($vau (env (filename))
      (eval env (cons $sequence (read-file filename)))
      #inert)))
  #inert)

($if ($binds? (get-current-environment) $set!) #inert
  ($provide! ($set!)
    ($define! $set! ($vau (dyn (env name value))
      (eval (eval dyn env) (list $define! name (list (unwrap eval) dyn value)))))))

($if ($binds? (get-current-environment) $remote-eval) #inert
  ($provide! ($remote-eval)
    ($define! $remote-eval ($vau (dyn (env expr))
      (eval (eval dyn env) expr)))))

($if ($binds? (get-current-environment) load)
  ($provide! (get-module)
    ($define! get-module ($lambda (filename . params)
      ($define! env (make-standard-environment))
      ($if (eq? params ()) #inert ($define! (params) params))
      ($if (eq? params ()) #inert ($set! env module-parameters params))
      (eval env (list load filename))
      env)))
  #inert)

($if ($binds? (get-current-environment) $jit-loop-head) #inert
  ($define! $jit-loop-head ($vau (#ignore #ignore) #inert)))
($if ($binds? (get-current-environment) jit-promote) #inert
  ($define! jit-promote ($lambda #ignore #inert)))
($if ($binds? (get-current-environment) debug-time-ms) #inert
  ($define! debug-time-ms ($lambda #ignore -1)))
($define! $debug-elapsed ($vau (env exprs)
  ($define! start (debug-time-ms))
  ($define! result (eval env (cons $sequence exprs)))
  ($define! end (debug-time-ms))
  (list (+ end (* -1 start)) result)))



