; Adapted from https://github.com/koka-lang/koka/blob/dev/test/bench/koka/cfold.kk
; type expr
  ; Var( : int )
($define! Var ($lambda (x) 0))
  ; Val( : int )
($define! Val ($lambda (x) x))
  ; Add( l : expr, r : expr )
($define! Add ($lambda (l r) (+ l r)))
  ; Mul( l : expr, r : expr )
($define! Mul ($lambda (l r) (* l r)))

($define! Var ((unwrap list) . Var))
($define! Val ((unwrap list) . Val))
($define! Add ((unwrap list) . Add))
($define! Mul ((unwrap list) . Mul))

($define! max ($lambda (a b) ($if (<=? a b) b a)))
($define! $match! ($vau (dyn (val vars . cases))
  ($define! memq? ($lambda (obj ls)
    ($if (pair? ls)
      ($if (eq? (car ls) obj)
           #t
           (memq? obj (cdr ls)))
      #f)))
  ($define! match? ($lambda (shape val env)
    ($cond
      ((eq? shape #ignore) #t)
      ((symbol? shape)
        ($cond
          ((memq? shape vars)
            (eval env (list $define! shape (cons (unwrap list) val)))
            #t)
          (#t
            (eq? (eval dyn shape) val))))
      ((pair? shape)
        ($cond
          ((pair? val)
            ($if (match? (car shape) (car val) env)
                 (match? (cdr shape) (cdr val) env)
                 #f))
          (#t #f)))
      (#t
        (eq? (eval dyn shape) val)))))
  ($define! match-helper ($lambda (val cases)
    ($define! env (make-environment))
    ($cond
      ((eq? cases ())
        #inert)
      (#t
        ($define! ((shape . then) . rest) cases)
        ($cond
          ((match? shape val env)
            (map ($lambda (var)
              ($if (eval env (list $binds? env var))
                (eval dyn (list $define! var (list (unwrap eval) env var)))
                #inert)) vars)
            (eval dyn (cons $sequence then)))
          (#t
            (match-helper val rest)))))))
  (match-helper (eval dyn val) cases)))

($define! mk_expr ($lambda (n v)  ; (int int) expr
  ($if (eq? n 0)
       ($if (eq? v 0) (list Var 1) (list Val v))
       (list Add (mk_expr (+ n -1) (+ v 1))
                 (mk_expr (+ n -1) (max (+ v -1) 0))))))

($define! append_add ($lambda (e0 e3)  ; (expr expr) expr
  ($match! e0 (e1 e2)
    ((Add e1 e2) (list Add e1 (append_add e2 e3)))
    (#ignore     (list Add e0 e3)))))

($define! append_mul ($lambda (e0 e3)  ; (expr expr) expr
  ($match! e0 (e1 e2)
    ((Mul e1 e2) (list Mul e1 (append_mul e2 e3)))
    (#ignore     (list Mul e0 e3)))))

($define! reassoc ($lambda (e)  ; (expr) expr
  ($match! e (e1 e2)
    ((Add e1 e2) (append_add (reassoc e1) (reassoc e2)))
    ((Mul e1 e2) (append_mul (reassoc e1) (reassoc e2)))
    (#ignore e))))

($define! cfold ($lambda (e)  ; (expr) expr
  ($match! e (e1 e2)
    ((Add e1 e2)
      ($define! e1' (cfold e1))
      ($define! e2' (cfold e2))
      ($match! e1' (a)
        ((Val a) ($match! e2' (b f)
          ((Val b) (list Val (+ a b)))
          ((Add f (Val b)) (list Add (list Val (+ a b)) f))
          ((Add (Val b) f) (list Add (list Val (+ a b)) f))
          (#ignore (list Add e1' e2'))))
        (#ignore (list Add e1' e2'))))
    ((Mul e1 e2)
      ($define! e1' (cfold e1))
      ($define! e2' (cfold e2))
      ($match! e1' (a)
        ((Val a) ($match! e2' (b f)
          ((Val b) (list Val (+ a b)))
          ((Mul f (Val b)) (list Mul (list Val (* a b)) f))
          ((Mul (Val b) f) (list Mul (list Val (* a b)) f))
          (#ignore (list Mul e1' e2'))))
        (#ignore (list Mul e1' e2'))))
    (#ignore e))))

($define! evaluate ($lambda (e)  ; (expr) int
  ($match! e (v l r)
    ((Var #ignore) 0)
    ((Val v) v)
    ((Add l r) (+ (evaluate l) (evaluate r)))
    ((Mul l r) (* (evaluate l) (evaluate r))))))

; pub fun test() : <div,console> ()
  ; repeat(100)
    ; val e = mk_expr(16,1)
    ; val v1 = eval(e)
    ; val v2 = e.reassoc.cfold.eval
    ; ()

($define! main ($lambda ()  ; (expr) int
  ($define! e (mk_expr 20 1))
  ($define! v1 (evaluate e))
  ($define! v2 (evaluate (cfold (reassoc e))))
  (list v1 v2)))
; (main)
