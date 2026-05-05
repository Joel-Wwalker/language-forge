; Canonical: stdlib. List, dict, range basics.
(def xs (list 1 2 3))
(print (len xs))
(print (get xs 1))

(def d (dict "k" 1 "v" 2))
(print (has d "k"))
(print (get d "v"))

(def r (range 5))
(print (len r))
