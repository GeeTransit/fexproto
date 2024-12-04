# wraps a function with zero, one, or more layers of argument evaluation
class Combiner:
    def __init__(self, num_wraps, func):
        assert num_wraps >= 0, f'expected non-negative wrap count, got {num_wraps}'
        self.num_wraps = num_wraps
        assert callable(func), f'combiner function is not callable: {func}'
        self.func = func

class Environment:
    def __init__(self, bindings, parent):
        assert type(bindings) is dict, f'bindings must be dict, got: {type(bindings)}'
        self.bindings = bindings
        assert type(parent) is Environment, f'parent must type Environment, got: {type(parent)}'
        self.parent = parent
Environment.ROOT = object.__new__(Environment)

class Continuation:
    def __init__(self, env, expr, parent):
        assert type(env) is Environment, f'env must be type Environment, got: {type(env)}'
        self.env = env
        self.expr = expr
        assert type(parent) is Continuation, f'parent must be type Continuation, got: {type(parent)}'
        self.parent = parent
Continuation.ROOT = object.__new__(Continuation)
Continuation.ERROR = Continuation(Environment.ROOT, None, Continuation.ROOT)

class Operative:
    def __init__(self, env, envname, name, body):
        assert type(env) is Environment, f'env must be type Environment, got: {type(env)}'
        self.env = env  # static environment (at time of declaration)
        assert type(envname) is str, f'envname must be type str, got: {type(envname)}'
        self.envname = envname  # name for dynamic environment
        assert type(name) is str, f'name must be type str, got: {type(name)}'
        self.name = name  # name for call arguments
        self.body = body  # function body
    def __call__(self, dyn, args, parent):
        # dyn is dynamic environment (at time of call)
        # args is call arguments
        # parent is parent continuation
        call_env = Environment({self.envname: dyn, self.name: args}, self.env)
        continuation = Continuation(call_env, self.body, parent)
        return continuation, None

class Pair:
    def __init__(self, car, cdr):
        self.car = car
        self.cdr = cdr
        self.immutable = False
    def __eq__(self, other):
        return self is other or (
            type(other) is Pair
            and self.car == other.car
            and self.cdr == other.cdr
        )

class Character:
    def __init__(self, char):
        assert type(char) is int, f'char must be type int, got: {type(char)}'
        assert 0 <= char < 256, f'char must be from 0 to 255, got: {char}'
        self.char = char
    def __eq__(self, other):
        return self is other or (
            type(other) is Character
            and self.char == other.char
        )

def f_eval(env, expr):
    if type(env) is dict:
        env = Environment(env, Environment.ROOT)
    continuation, value = Continuation(env, expr, Continuation.ROOT), None
    while continuation is not Continuation.ROOT:
        continuation, value = step_evaluate(continuation, value)
        if continuation is Continuation.ERROR:
            raise ValueError(value)
    return value

def _f_error(parent, *args):
    error_applicative = Pair(Combiner(1, _operative_continuation_to_applicative), Pair(Continuation.ERROR, ()))
    error_operative = Pair(Combiner(1, _operative_unwrap), Pair(error_applicative, ()))
    message_tree = ()
    for arg in reversed(args): message_tree = Pair(arg, message_tree)
    expr = Pair(error_operative, message_tree)
    continuation = Continuation(Environment.ROOT, expr, parent)
    return continuation, None

def _f_copy_es(obj, *, seen=None, immutable=False):
    if type(obj) is not Pair:
        return obj
    if obj.immutable:
        return obj
    if seen is None:
        seen = {}
    if id(obj) in seen:
        return seen[id(obj)]
    pair = Pair((), ())
    seen[id(obj)] = pair
    pair.car = _f_copy_es(obj.car, seen=seen, immutable=immutable)
    pair.cdr = _f_copy_es(obj.cdr, seen=seen, immutable=immutable)
    pair.immutable = immutable
    if immutable and hasattr(obj, "_location_info"):
        pair._location_info = obj._location_info
    return pair

def _f_write(obj):
    seen = {}
    def _recursive_write(obj, depth):
        if type(obj) is tuple:
            print(end="()")
        elif type(obj) is Pair:
            if id(obj) in seen:
                seen_depth = seen[id(obj)]
                print(end="#"+"."*(depth - seen_depth))
            else:
                start_depth = depth
                remove = []
                seen[id(obj)] = depth
                remove.append(id(obj))
                print(end="(")
                _recursive_write(obj.car, depth+1)
                depth += 1
                obj = obj.cdr
                while type(obj) is Pair:
                    if id(obj) in seen:
                        break
                    seen[id(obj)] = depth
                    remove.append(id(obj))
                    print(end=" ")
                    _recursive_write(obj.car, depth+1)
                    depth += 1
                    obj = obj.cdr
                if type(obj) is not tuple:
                    print(end=" . ")
                    _recursive_write(obj, depth)
                print(end=")")
                for remove_obj in remove:
                    del seen[remove_obj]
        elif type(obj) in (int, float):
            print(end=repr(obj))
        elif type(obj) is str:
            print(end=obj)
        elif type(obj) is bytes:
            print(end='"')
            for char in obj:
                if char != b'"'[0]:
                    print(end=repr(bytes([char]))[2:-1])
                else:
                    print(end=r'\"')
            print(end='"')
        elif type(obj) is Character:
            i = b" ()\t\n\r".find(obj.char)
            if i == -1:
                out = repr(bytes([obj.char]))[2:-1]
                if out[0] == "\\":
                    print(end="#"+out)
                else:
                    print(end="#\\"+out)
            else:
                print(end=(r"#\x20", r"#\x28", r"#\x29", r"#\x09", r"#\x0a", r"#\x0d")[i])
        elif type(obj) in (Environment, Continuation, Combiner):
            print(end="#"+repr(obj))
        elif type(obj) is type(...):
            print(end="#ignore")
        elif type(obj) is type(None):
            print(end="#inert")
        elif type(obj) is bool:
            print(end="#t" if obj else "#f")
        else:
            print(end="#unknown"+repr(obj))
    _recursive_write(obj, 0)

# given a continuation and a value, get the next continuation and value
def step_evaluate(continuation, value):
    env = continuation.env
    expr = continuation.expr
    parent = continuation.parent
    if type(expr) is str:
        while env is not Environment.ROOT:
            if expr in env.bindings:
                return parent, env.bindings[expr]
            env = env.parent
        return _f_error(parent, b"binding not found: ", expr)
    elif type(expr) is Pair:
        name, args = expr.car, expr.cdr
        if type(name) is Pair and name.car is name:
            return _f_error(parent, b"infinite recursive evaluation of combiner detected")
        # evaluate car of call
        next_env = Environment({"env": env, "args": args}, Environment.ROOT)
        continuation = Continuation(next_env, _step_call_wrapped, parent)
        continuation = Continuation(Environment.ROOT, _step_call_combcar, continuation)
        continuation = Continuation(env, name, continuation)
        return continuation, None
    elif type(expr) in (int, float, Combiner, bytes, type(...), bool, type(None), Continuation, Environment, tuple, Character):
        return parent, expr
    elif callable(expr):
        return expr(env, value, parent=parent)
    else:
        return _f_error(parent, b"unknown expression type: ", expr)

# return (number of Pairs, number of Nils, Acyclic prefix length, Cycle length)
def _get_list_metrics(obj):
    if type(obj) is not Pair:
        return 0, (1 if obj == () else 0), 0, 0
    hare_distance = hare_power = 1
    list_length = 0
    tortoise = obj
    hare = obj.cdr
    if type(hare) is not Pair:
        return list_length + hare_distance, (1 if hare == () else 0), list_length + hare_distance, 0
    # Brent's cycle detection algorithm
    while tortoise is not hare:
        if hare_distance == hare_power:
            tortoise = hare
            hare_power *= 2
            list_length += hare_distance
            hare_distance = 0
        hare = hare.cdr
        hare_distance += 1
        if type(hare) is not Pair:
            return list_length + hare_distance, (1 if hare == () else 0), list_length + hare_distance, 0
    tortoise = hare = obj
    for _ in range(hare_distance):
        hare = hare.cdr
    offset = 0
    while tortoise is not hare:
        tortoise = tortoise.cdr
        hare = hare.cdr
        offset += 1
    return offset + hare_distance, 0, offset, hare_distance

# if c is nonzero, set the a+c-1th pair's cdr to the ath pair
def _step_encycle(env, args, parent):
    a = env.bindings["a"]
    c = env.bindings["c"]
    if c == 0:
        return parent, args
    for _ in range(a):
        args = args.cdr
    head = args
    for _ in range(c - 1):
        args = args.cdr
    args.cdr = head
    return parent, args

def _step_call_combcar(_env, value, parent):
    if type(value) is not Combiner:
        return _f_error(parent, b"expected combiner as car of combiner call, got: ", value)
    return parent, value

# evaluate arguments based on num_wraps
def _step_call_wrapped(static, combiner, parent):
    env = static.bindings["env"]
    args = static.bindings["args"]
    assert type(combiner) is Combiner
    continuation = Continuation(env, combiner.func, parent)
    if combiner.num_wraps == 0:
        return continuation, args
    p, n, a, c = _get_list_metrics(args)
    if n == c == 0:
        return _f_error(parent, b"applicative arguments must be proper list, got: ", args)
    encycle_env = Environment({"a": a, "c": c}, Environment.ROOT)
    continuation = Continuation(encycle_env, _step_encycle, continuation)
    next_env = Environment({"env": env, "num_wraps": combiner.num_wraps, "p": p}, Environment.ROOT)
    continuation = Continuation(next_env, _step_call_evlis, continuation)
    return continuation, args

# evaluate each element in the list
def _step_call_evlis(static, args, parent):
    num_wraps = static.bindings["num_wraps"]
    env = static.bindings["env"]
    p = static.bindings["p"]
    if num_wraps > 0:
        next_env = Environment({"env": env, "num_wraps": num_wraps - 1, "p": p}, Environment.ROOT)
        continuation = Continuation(next_env, _step_call_evlis, parent)
        evcar_env = Environment({"env": env, "p": p, "pending": args, "done": (), "started": False}, Environment.ROOT)
        continuation = Continuation(evcar_env, _step_call_evcar, continuation)
        return continuation, None
    else:
        return parent, args

def _step_call_evcar(static, value, parent):
    env = static.bindings["env"]
    p = static.bindings["p"]
    pending = static.bindings["pending"]
    done = static.bindings["done"]
    started = static.bindings["started"]
    if started:
        done = Pair(value, done)
    else:
        static.bindings["started"] = True
    if p > 0:
        # append the previous result and evaluate the next element
        static.bindings["p"] -= 1
        static.bindings["pending"] = pending.cdr
        static.bindings["done"] = done
        continuation = Continuation(static, _step_call_evcar, parent)
        continuation = Continuation(env, pending.car, continuation)
        return continuation, None
    else:
        args = ()
        while done != (): args, done = Pair(done.car, args), done.cdr
        return parent, args

# load a file in an environment
def _f_load(env, expr, *, parent=None):
    with open(expr.decode("utf-8")) as file:
        text = file.read()
    tokens = tokenize(text)
    try:
        exprs = parse(tokens, filename=expr.decode("utf-8"))
    except ValueError as e:
        return _f_error(parent, repr(e).encode("utf-8"))
    args = ()
    for expr in reversed(exprs): args = Pair(expr, args)
    continuation = Continuation(env, None, parent)
    next_env = Environment({"env": env, "num_wraps": 1, "p": len(exprs)}, Environment.ROOT)
    continuation = Continuation(next_env, _step_call_evlis, continuation)
    return continuation, args

# modify environment according to name
def _f_define(static, expr, parent):
    env = static.bindings["env"]
    name = static.bindings["name"]
    env.bindings[name] = expr
    return parent, None

def _f_if(env, result, parent):
    if result is True:
        on_true = env.bindings["on_true"]
        env = env.bindings["env"]
        return Continuation(env, on_true, parent), None
    if result is False:
        on_false = env.bindings["on_false"]
        env = env.bindings["env"]
        return Continuation(env, on_false, parent), None
    return _f_error(parent, b"expected #t or #f as condition for $if, got: ", result)

def _f_abnormal_pass(env, _value, parent):
    return env.parent.bindings["continuation"], env.bindings["value"]

def _operative_number(env, expr, parent):
    return parent, type(expr.car) in (int, float)

def _operative_symbol(env, expr, parent):
    return parent, type(expr.car) is str

def _operative_symbol_to_string(env, expr, parent):
    return parent, expr.car.encode("latin-1")

def _operative_string_to_symbol(env, expr, parent):
    return parent, expr.car.decode("latin-1")

def _operative_plus(env, expr, parent):
    return parent, expr.car + expr.cdr.car

def _operative_lessequal(env, expr, parent):
    return parent, expr.car <= expr.cdr.car

def _operative_vau(env, expr, parent):
    # ($vau (envname name) body)
    operative = Operative(env=env, envname=expr.car.car, name=expr.car.cdr.car, body=_f_copy_es(expr.cdr.car, immutable=True))
    return parent, Combiner(0, operative)

def _operative_eval(env, expr, parent):
    continuation = Continuation(expr.car, expr.cdr.car, parent)
    return continuation, None

def _operative_wrap(env, expr, parent):
    return parent, Combiner(expr.car.num_wraps + 1, expr.car.func)

def _operative_unwrap(env, expr, parent):
    return parent, Combiner(expr.car.num_wraps - 1, expr.car.func)

def _operative_define(env, expr, parent):
    next_env = Environment({"env": env, "name": expr.car}, Environment.ROOT)
    continuation = Continuation(next_env, _f_define, parent)
    continuation = Continuation(env, expr.cdr.car, continuation)
    return continuation, None

def _operative_car(env, expr, parent):
    return parent, expr.car.car

def _operative_cdr(env, expr, parent):
    return parent, expr.car.cdr

def _operative_cons(env, expr, parent):
    return parent, Pair(expr.car, expr.cdr.car)

def _operative_set_car(env, expr, parent):
    if expr.car.immutable:
        return _f_error(parent, b"pair must be mutable")
    expr.car.car = expr.cdr.car
    return parent, None

def _operative_set_cdr(env, expr, parent):
    if expr.car.immutable:
        return _f_error(parent, b"pair must be mutable")
    expr.car.cdr = expr.cdr.car
    return parent, None

def _operative_copy_es(env, expr, parent):
    return parent, _f_copy_es(expr.car)

def _operative_copy_es_immutable(env, expr, parent):
    return parent, _f_copy_es(expr.car, immutable=True)

def _operative_load(env, expr, parent):
    continuation = Continuation(env, _f_load, parent)
    return continuation, expr.car

def _operative_if(env, expr, parent):
    next_env = Environment({"env": env, "on_true": expr.cdr.car, "on_false": expr.cdr.cdr.car}, Environment.ROOT)
    continuation = Continuation(next_env, _f_if, parent)
    continuation = Continuation(env, expr.car, continuation)
    return continuation, None

def _operative_eq(env, expr, parent):
    return (parent,
        expr.car == expr.cdr.car
        if type(expr.car) is type(expr.cdr.car) in (str, int, float, bytes, Character)
        else expr.car is expr.cdr.car
    )

def _operative_pair(env, expr, parent):
    return parent, type(expr.car) is Pair

def _operative_environment(env, expr, parent):
    return parent, type(expr.car) is Environment

def _operative_make_environment(_env, expr, parent):
    parent_env = expr.car if expr != () else Environment.ROOT
    return parent, Environment({}, parent_env)

def _operative_continuation(env, expr, parent):
    return parent, type(expr.car) is Continuation

def _operative_continuation_to_applicative(_env, expr, parent):
    continuation = expr.car
    if type(continuation) is not Continuation:
        return _f_error(parent, b"continuation must be type Continuation, got: ", continuation)
    env = Environment({"continuation": continuation}, Environment.ROOT)
    operative = Operative(env, "_", "value", _f_abnormal_pass)
    return parent, Combiner(1, operative)

def _operative_call_cc(env, expr, parent):
    continuation = Continuation(env, Pair(expr.car, Pair(parent, ())), parent)
    return continuation, None

def _operative_extend_continuation(env, expr, parent):
    continuation = expr.car
    applicative = expr.cdr.car
    environment = expr.cdr.cdr.car if expr.cdr.cdr != () else Environment({}, Environment.ROOT)
    if applicative.num_wraps != 1:
        return _f_error(parent, b"applicative unwrapped must be an operative")
    new_continuation = Continuation(environment, applicative.func, continuation)
    return parent, new_continuation

def _operative_char(env, expr, parent):
    return parent, type(expr.car) is Character

def _operative_read_char(env, expr, parent):
    import sys
    char = sys.stdin.buffer.read(1)
    if not char:
        return _f_error(parent, b"end of file reached")
    return parent, Character(char[0])

def _operative_write_char(env, expr, parent):
    import sys
    sys.stdout.buffer.write(bytes([expr.car.char]))
    return parent, None

def _operative_string(env, expr, parent):
    return parent, type(expr.car) is bytes

def _operative_list_to_string(env, expr, parent):
    chars = expr.car
    p, n, a, c = _get_list_metrics(chars)
    if n == 0 or c > 0:
        return _f_error(parent, b"list->string argument must be finite list, got: ", chars)
    string = bytearray()
    for _ in range(a):
        string.append(chars.car.char)
        chars = chars.cdr
    return parent, bytes(string)

def _operative_string_to_list(env, expr, parent):
    string = expr.car
    if not len(string):
        return parent, ()
    chars = Pair(Character(string[0]), ())
    curr = chars
    for char in memoryview(string[1:]):
        curr.cdr = curr = Pair(Character(char), ())
    return parent, chars

_DEFAULT_ENV = {
    "number?": Combiner(1, _operative_number),
    "symbol?": Combiner(1, _operative_symbol),
    "symbol->string": Combiner(1, _operative_symbol_to_string),
    "string->symbol": Combiner(1, _operative_string_to_symbol),
    "+": Combiner(1, _operative_plus),
    "<=?": Combiner(1, _operative_lessequal),
    "$vau": Combiner(0, _operative_vau),
    "eval": Combiner(1, _operative_eval),
    "wrap": Combiner(1, _operative_wrap),
    "unwrap": Combiner(1, _operative_unwrap),
    "$define!": Combiner(0, _operative_define),
    "car": Combiner(1, _operative_car),
    "cdr": Combiner(1, _operative_cdr),
    "cons": Combiner(1, _operative_cons),
    "set-car!": Combiner(1, _operative_set_car),
    "set-cdr!": Combiner(1, _operative_set_cdr),
    "copy-es": Combiner(1, _operative_copy_es),
    "copy-es-immutable": Combiner(1, _operative_copy_es_immutable),
    "load": Combiner(1, _operative_load),
    "$if": Combiner(0, _operative_if),
    "eq?": Combiner(1, _operative_eq),
    "pair?": Combiner(1, _operative_pair),
    "environment?": Combiner(1, _operative_environment),
    "make-environment": Combiner(1, _operative_make_environment),
    "continuation?": Combiner(1, _operative_continuation),
    "continuation->applicative": Combiner(1, _operative_continuation_to_applicative),
    "call/cc": Combiner(1, _operative_call_cc),
    "extend-continuation": Combiner(1, _operative_extend_continuation),
    "error-continuation": Continuation.ERROR,
    "char?": Combiner(1, _operative_char),
    "read-char": Combiner(1, _operative_read_char),
    "write-char": Combiner(1, _operative_write_char),
    "string?": Combiner(1, _operative_string),
    "list->string": Combiner(1, _operative_list_to_string),
    "string->list": Combiner(1, _operative_string_to_list),
}

def tokenize(text):
    return text.encode("utf-8")

def parse(tokens, filename="\x00parse"):
    exprs = []
    chars = (tokens[i:i+1] for i in range(len(tokens)+1))
    reader = _Reader(lambda: next(chars), filename)
    while True:
        try:
            expr = reader.read()
        except EOFError:
            break
        expr = _f_copy_es(expr, immutable=True)
        exprs.append(expr)
    return exprs

class _Reader:
    # get_next_char is a callable that returns a length 0 or 1 bytes object
    def __init__(self, get_next_char, filename):
        self.get_next_char = get_next_char
        self.pos = 0
        self.line_no = 1
        self.char_no = 0
        self._curr = None
        self._cons = []
        self.filename = filename

    def read(self):
        self._skip_whitespace()
        if self.curr == b"":
            raise EOFError("end of file reached")
        return self._read()

    # Returns the current value from get_next_char
    @property
    def curr(self):
        if self._curr is None:
            try:
                self._curr = self.get_next_char()
            except EOFError:
                self._curr = b""
            self.pos += 1
            if self._curr == b"\n":
                self.line_no += 1
                self.char_no = 0
            else:
                self.char_no += 1
        return self._curr

    # Returns the next value from get_next_char
    @property
    def next(self):
        if self._curr == b"":
            raise ValueError("reading past end of file")
        self._curr = None
        return self.curr

    def push_cons(self):
        top = Pair((), ())
        self._cons.append(top)
        top._location_info = [self.filename, self.line_no, self.char_no, -1, -1]
        return top

    def pop_cons(self, same_as):
        assert same_as is self._cons[-1]
        top = self._cons.pop()
        top._location_info[3:5] = self.line_no, self.char_no
        return top

    def _skip_whitespace(self):
        while True:
            if self.curr and self.curr in b" \t\r\n":
                self.next
            elif self.curr == b";":  # Comments take up the rest of the line
                while self.curr and self.curr != b"\n":
                    self.next
            else:
                break

    def _read(self):
        if self.curr == b'"':
            return self._read_string()
        elif self.curr == b"(":
            start_info = self.line_no, self.char_no
            self.next
            self._skip_whitespace()
            if self.curr == b")":
                self.next
                return ()
            top = self._read_elements(True)
            # Update debug info to start on the left bracket
            top._location_info[1:3] = start_info
            self._skip_whitespace()
            if self.curr == b")":
                self.next
                return top
            raise ValueError(f'expected close bracket, got {self.curr}')
        elif self.curr == b")":
            raise ValueError("unexpected close bracket")
        elif self.curr == b" ":
            self._skip_whitespace()
            return self._read()
        elif not self.curr:
            raise ValueError(f'unexpected end of file')
        else:
            return self._read_literal()

    def _read_elements(self, first):
        if not first:
            if self.curr == b")":
                return ()
            if self.curr == b".":
                self.next
                self._skip_whitespace()
                return self._read()
        top = self.push_cons()
        top.car = self._read()
        self._skip_whitespace()
        top.cdr = self._read_elements(False)
        return self.pop_cons(same_as=top)

    def _read_string(self):
        assert self.curr == b'"'
        string_info = f'string starting at line {self.line_no} char {self.char_no}'
        self.next
        string = bytearray()
        while self.curr != b'"':
            if not self.curr:
                raise ValueError(f'unexpected end of file in {string_info}')
            if self.curr == b"\\":
                self.next
                if not self.curr:
                    raise ValueError(f'unexpected end of escape sequence in {string_info}')
                if self.curr in b"\\'\"":
                    string.extend(self.curr)
                    self.next
                elif self.curr in b"abfnrtv":
                    string.append(b"\a\b\f\n\r\t\v"[b"abfnrtv".index(self.curr)])
                    self.next
                elif self.curr in b"xuU":
                    initial = self.curr
                    self.next
                    chars = bytearray()
                    for _ in range((2, 4, 8)[b"xuU".index(initial)]):
                        if not self.curr: raise ValueError(f'unexpected end of escape sequence in {string_info}')
                        chars.extend(self.curr)
                        self.next
                    value = 0
                    for char in chars:
                        if char not in b"0123456789abcdefABCDEF":
                            raise ValueError(f'invalid \\{initial.decode()} escape sequence in {string_info}: {chars}')
                        value = value*16 + b"0123456789abcdef".index(bytes([char]).lower())
                    if initial == b"x":
                        string.append(value)
                    else:
                        string.extend(chr(value).encode("utf-8"))
                else:
                    raise ValueError(f'unknown escape sequence in {string_info}: {self.curr}')
            else:
                string.extend(self.curr)
                self.next
        self.next
        return bytes(string)

    def _read_literal(self):
        const_info = f'literal starting at line {self.line_no} char {self.char_no}'
        chars = bytearray()
        while True:
            chars.extend(self.curr)
            self.next
            if not self.curr or self.curr in b" \t\r\n();":
                break
        if chars[0] == b"#"[0]:  # constants
            if chars == b"#t": return True
            if chars == b"#f": return False
            if chars == b"#inert": return None
            if chars == b"#ignore": return ...
            if len(chars) >= 2 and chars[1] == b"\\"[0]:
                if len(chars) == 3:
                    return Character(chars[2])
                if len(chars) >= 3 and chars[2] == b"x"[0]:
                    if len(chars) != 5:
                        raise ValueError(f'invalid character {const_info}: {chars}')
                    value = 0
                    for char in chars[3:]:
                        if char not in b"0123456789abcdefABCDEF":
                            raise ValueError(f'invalid \\x escape sequence in character {const_info}: {chars}')
                        value = value*16 + b"0123456789abcdef".index(bytes([char]).lower())
                    return Character(value)
                raise ValueError(f'invalid character {const_info}: {chars}')
            if len(chars) >= 2 and chars[1] == b"."[0]:
                if not all(char == b"."[0] for char in chars[1:]):
                    raise ValueError(f'invalid self-reference {const_info}: {chars}')
                if len(chars)-1 >= len(self._cons):
                    raise ValueError(f'self-reference {const_info} references past the root element')
                return self._cons[-(len(chars)-1)]
            raise ValueError(f'unknown {const_info}: {chars}')
        if chars[0] in b"0123456789" or chars[0] in b"-+" and len(chars) >= 2 and chars[1] in b"0123456789":
            chars = chars.decode("latin1")
            try:
                return int(chars)
            except ValueError:
                return float(chars)
        return chars.decode("utf-8").lower()  # Symbols are lowercase


# make a standard environment (should be constant)
def _make_standard_environment(*, primitives=None):
    if primitives is None:
        primitives = _DEFAULT_ENV

    # create standard environment with primitives as parent
    env = Environment(primitives, Environment.ROOT)
    env = Environment({}, env)

    # get standard library
    with open("std.lisp") as file:
        text = file.read()
    tokens = tokenize(text)
    exprs = parse(tokens, filename="std.lisp")

    # evaluate in standard environment
    for expr in exprs:
        continuation, value = Continuation(env, expr, Continuation.ROOT), None
        while continuation is not Continuation.ROOT:
            continuation, value = step_evaluate(continuation, value)
            if continuation is Continuation.ERROR:
                raise ValueError(value)

    # return child of standard environment
    env = Environment({}, env)
    return env

def main(env=None):
    import sys
    with open(sys.argv[1] if len(sys.argv) >= 2 else 0) as file:
        text = file.read()
    tokens = tokenize(text)
    try:
        exprs = parse(tokens, filename=sys.argv[1] if len(sys.argv) >= 2 else "\x00stdin")
    except ValueError as e:
        exit(e)
    if env is None:
        env = _make_standard_environment()
    if type(env) is dict:
        env = Environment(env, Environment.ROOT)
    for expr in exprs:
        continuation, value = Continuation(env, expr, Continuation.ROOT), None
        while continuation is not Continuation.ROOT:
            continuation, value = step_evaluate(continuation, value)
            if continuation is Continuation.ERROR:
                print(end="! ");_f_write(Pair("error", value));print()
                exit(1)
        print(end="> ");_f_write(value);print()

if __name__ == "__main__":
    main()
