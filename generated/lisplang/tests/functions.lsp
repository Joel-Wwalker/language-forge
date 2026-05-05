; Canonical: functions. Definition, call, recursion.
(defn add (a b)
  (+ a b))

(defn factorial (n)
  (if (<= n 1)
      1
      (* n (factorial (- n 1)))))

(print (add 3 4))
(print (factorial 5))
