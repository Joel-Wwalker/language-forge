\ Canonical: stdlib. Stack ops are forthlang's stdlib.
1 2 swap . .         \ swap top two: prints 1, then 2
1 2 over . . .       \ ( a b -- a b a ): prints 1 2 1
1 2 3 rot . . .      \ ( a b c -- b c a ): prints 1 3 2

3 dup * .            \ duplicate-then-multiply: 9
