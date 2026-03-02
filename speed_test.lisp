; Simple tail recursive function where (sumto n 0) returns the sum of 1 to n
($define! sumto ($lambda (n acc)
	($sequence
		($jit-loop-head sumto)
		($if (eq? 0 n)
			acc
			(sumto (+ n -1) (+ acc n))))))

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
