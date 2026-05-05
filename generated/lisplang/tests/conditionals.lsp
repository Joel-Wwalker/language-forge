; Canonical: conditionals.
(def n 7)
(if (> n 0)
    (print "positive")
    (print "non-positive"))

(if (= n 0)
    (print "zero")
    (if (> n 0)
        (print "positive")
        (print "negative")))

(when (< n 100)
  (print "small"))
