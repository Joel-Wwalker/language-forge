\ Canonical: closures. Forth doesn't have lexical closures (no nested
\ scopes); the equivalent pattern is a word that captures + mutates
\ a module-level variable. Same algorithm, different mechanism.
variable counter
0 counter !

: tick ( -- )
    counter @ 1 + counter ! ;

: show ( -- )
    counter @ . ;

tick show
tick show
tick show
