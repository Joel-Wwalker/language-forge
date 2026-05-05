(defn max_depth (root)
    (do
        (if (= root nil)
        (return 0)
        nil)
        (def l (max_depth (get root "left")))
        (def r (max_depth (get root "right")))
        (if (> l r)
        (return (+ l 1))
        nil)
        (return (+ r 1))))

(print (max_depth (node 1 (leaf 2) (leaf 3))))
