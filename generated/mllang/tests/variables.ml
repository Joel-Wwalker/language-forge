(* Canonical: variables - top-level let bindings + nested let-in. *)
let x = 10 ;;
let y = 20 ;;
print_int (x + y) ;;
print_newline () ;;

let z = let a = 5 in a * 2 ;;
print_int z ;;
print_newline () ;;
