(* Canonical: loops - recursion over a list, ML-natural. mllang has no
   while/for; iteration is recursion on list cons. *)
let rec sum lst = match lst with
  | [] -> 0
  | h :: t -> h + sum t
;;

let rec count_down n =
  if n < 0 then ()
  else (
    print_int n ;
    print_newline () ;
    count_down (n - 1)
  )
;;

print_int (sum [1; 2; 3; 4; 5]) ;;
print_newline () ;;
count_down 3 ;;
