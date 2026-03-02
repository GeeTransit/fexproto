Copyright (C) 2024-2026 George Zhang

See the end of the file for license conditions.

# fexproto

Not yet finished implementation of John Shutt's [Kernel language](https://web.cs.wpi.edu/~jshutt/kernel.html) in Python 3.7+.

Another implementation using the [RPython toolchain](https://rpython.readthedocs.io/en/latest/) is also being worked on and is source compatible with both Python 2.7 and 3.7+.

Note that `$vau` and `eval` have slightly different parameters and environments have only one parent.

## Quickstart

Ensure [Git](https://git-scm.com/) and [Python 3.7+](https://www.python.org/) are installed.
```sh
git clone https://github.com/GeeTransit/fexproto
cd fexproto
python3 fexproto.py
```

Try defining and using your own operative:
```lisp
; ($match ANY ...(ANY ...EXPR))
($define! $match ($vau (env (expr . cases))
  ($define! value (eval env expr))
  ($define! helper ($lambda (value cases)
    ($cond ((eq? cases ()) #inert)
           (#t ($define! ((case . then) . rest) cases)
               ($if (equal? (eval env case) value)
                    (apply (wrap $sequence) then env)
                    (helper value rest))))))
  (helper value cases)))
($match (<=? 3 2)
        ((+ 9 10) 21)
        ("six" "seven")
        (#f ($define! cyclic (list 1 2 3))
            (set-cdr! (cddr cyclic) cyclic)
            ($define! (#ignore . second) cyclic)
            second))
```

## RPython implementation

Ensure Python 2.7 is installed.
```sh
python2 rfexproto.py -i std.lisp
```

For translation, ensure [PyPy 2.7](https://pypy.org/) is installed (CPython 2.7 will not work).

Clone the RPython toolchain, translate, and start the REPL.
```sh
git clone --depth=1 https://github.com/pypy/pypy.git
pypy2 pypy/rpython/bin/rpython rfexproto.py
./rfexproto-c -i std.lisp
```

Translating with a JIT included is similar.
```sh
pypy2 pypy/rpython/bin/rpython -Ojit rfexproto.py
./rfexproto-c-jit -i std.lisp
```

## License

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
