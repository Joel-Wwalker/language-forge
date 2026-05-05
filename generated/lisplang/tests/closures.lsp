; Canonical: closures. Function returning a function that captures + mutates a binding.
(defn make-counter ()
  (def count 0)
  (fn ()
    (set! count (+ count 1))
    count))

(def counter (make-counter))
(print (counter))
(print (counter))
(print (counter))

; Independent counters don't share state.
(def other (make-counter))
(print (other))
(print (counter))
