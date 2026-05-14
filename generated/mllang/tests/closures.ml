(* Canonical: closures - first-class functions that close over variables.
   make_adder captures its parameter `n` and returns a closure. Each call
   to make_adder produces an independent closure. *)
let make_adder n = fun x -> x + n ;;
let add5 = make_adder 5 ;;
let add10 = make_adder 10 ;;
print_int (add5 3) ;;
print_newline () ;;
print_int (add5 100) ;;
print_newline () ;;
print_int (add10 3) ;;
print_newline () ;;
print_int (add10 (add5 0)) ;;
print_newline () ;;
