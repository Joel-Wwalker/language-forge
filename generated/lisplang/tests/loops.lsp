; Canonical: loops. Sum 1..10 imperatively.
(def i 1)
(def total 0)
(while (<= i 10)
  (set! total (+ total i))
  (set! i (+ i 1)))
(print total)
