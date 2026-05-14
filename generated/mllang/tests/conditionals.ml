(* Canonical: conditionals - if-then-else AND match on integer literals. *)
let x = 5 ;;
let msg = if x > 3 then "big" else "small" ;;
print_string msg ;;
print_newline () ;;

let describe n = match n with
  | 0 -> "zero"
  | 1 -> "one"
  | _ -> "many"
;;

print_string (describe 0) ;;
print_newline () ;;
print_string (describe 1) ;;
print_newline () ;;
print_string (describe 42) ;;
print_newline () ;;
