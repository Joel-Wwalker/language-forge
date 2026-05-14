(* Canonical: functions - curried definition + recursion via let rec. *)
let add a b = a + b ;;
print_int (add 2 3) ;;
print_newline () ;;

let rec fact n = if n <= 1 then 1 else n * fact (n - 1) ;;
print_int (fact 5) ;;
print_newline () ;;
print_int (fact 10) ;;
print_newline () ;;
