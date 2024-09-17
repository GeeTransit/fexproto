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
        # evaluate car of call
        next_env = Environment({"env": env, "args": args}, Environment.ROOT)
        continuation = Continuation(next_env, _step_call_wrapped, parent)
        continuation = Continuation(env, name, continuation)
        return continuation, None
    elif type(expr) in (int, float, Combiner, bytes, type(...), bool, type(None), Continuation, Environment, tuple):
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

# evaluate arguments based on num_wraps
def _step_call_wrapped(static, combiner, parent):
    env = static.bindings["env"]
    args = static.bindings["args"]
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
        exprs = parse(tokens)
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

def _operative_plus(env, expr, parent):
    return parent, expr.car + expr.cdr.car

def _operative_vau(env, expr, parent):
    # ($vau (envname name) body)
    operative = Operative(env=env, envname=expr.car.car, name=expr.car.cdr.car, body=expr.cdr.car)
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
        if type(expr.car) is type(expr.cdr.car) in (str, int, float, bytes)
        else expr.car is expr.cdr.car
    )

def _operative_pair(env, expr, parent):
    return parent, type(expr.car) is Pair

def _operative_make_environment(_env, expr, parent):
    parent_env = expr.car if expr != () else Environment.ROOT
    return parent, Environment({}, parent_env)

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

_DEFAULT_ENV = {
    "+": Combiner(1, _operative_plus),
    "$vau": Combiner(0, _operative_vau),
    "eval": Combiner(1, _operative_eval),
    "wrap": Combiner(1, _operative_wrap),
    "unwrap": Combiner(1, _operative_unwrap),
    "$define!": Combiner(0, _operative_define),
    "car": Combiner(1, _operative_car),
    "cdr": Combiner(1, _operative_cdr),
    "cons": Combiner(1, _operative_cons),
    "load": Combiner(1, _operative_load),
    "$if": Combiner(0, _operative_if),
    "eq?": Combiner(1, _operative_eq),
    "pair?": Combiner(1, _operative_pair),
    "make-environment": Combiner(1, _operative_make_environment),
    "continuation->applicative": Combiner(1, _operative_continuation_to_applicative),
    "call/cc": Combiner(1, _operative_call_cc),
    "error-continuation": Continuation.ERROR,
}

def tokenize(text):
    return text.replace("(", " ( ").replace(")", " ) ").split()

def parse(tokens):
    exprs = []
    expr_stack = []
    pair_stack = []
    field_stack = []
    for token in tokens:
        if token == "(":
            # Update pair for new element
            if expr_stack:
                if field_stack[-1] is None:
                    raise ValueError("unexpected element after cdr element")
                if field_stack[-1] == "car":
                    pair = Pair((), ())
                    pair_stack.append(pair)
                    if expr_stack[-1] > 0:
                        pair_stack[-2].cdr = pair
                    elif len(expr_stack) >= 2:
                        if field_stack[-2] == "cdr":
                            pair_stack[-2].cdr = pair
                        else:
                            pair_stack[-2].car = pair
                    expr_stack[-1] += 1
            expr_stack.append(0)
            field_stack.append("car")
        elif token == ")":
            if not expr_stack:
                raise ValueError("unmatched close bracket")
            if field_stack[-1] == "cdr":
                raise ValueError("unexpected close bracket after dot")
            field_stack.pop()
            expr = ()
            for _ in range(expr_stack.pop()):
                expr = pair_stack.pop()
            # Update parent pair with list
            if expr_stack:
                if field_stack[-1] == "cdr":
                    pair_stack[-1].cdr = expr
                    field_stack[-1] = None
                else:
                    pair_stack[-1].car = expr
            else:
                exprs.append(expr)
        elif token == ".":
            if not expr_stack:
                raise ValueError("unexpected dot outside of list")
            if expr_stack[-1] == 0:
                raise ValueError("unexpected dot as first element of list")
            if field_stack[-1] == "cdr":
                raise ValueError("unexpected dot after dot")
            if field_stack[-1] is None:
                raise ValueError("unexpected dot after cdr element")
            field_stack[-1] = "cdr"
        else:
            # Update parent pair for new element
            if expr_stack:
                if field_stack[-1] is None:
                    raise ValueError("unexpected element after cdr element")
                if field_stack[-1] == "car":
                    pair = Pair((), ())
                    pair_stack.append(pair)
                    if expr_stack[-1] > 0:
                        pair_stack[-2].cdr = pair
                    elif len(expr_stack) >= 2:
                        if field_stack[-2] == "cdr":
                            pair_stack[-2].cdr = pair
                        else:
                            pair_stack[-2].car = pair
                    expr_stack[-1] += 1
            # Parse token
            if token[0] == '"' and token[-1] == '"' and len(token) >= 2:
                token = token[1:-1].encode("raw_unicode_escape").decode("unicode_escape").encode("utf-8")
            elif token[:2] == "#.":
                assert all(char == "." for char in token[1:]), "reference must only contain dots"
                up = len(token) - 1
                if up > len(pair_stack):
                    raise ValueError("reference points outside of structure")
                token = pair_stack[-up]
            elif token == "#ignore":
                token = ...
            elif token == "#inert":
                token = None
            elif token in ("#t", "#f"):
                token = token == "#t"
            else:
                try:
                    token = float(token)
                except ValueError:
                    token = token.lower()
                else:
                    try:
                        token = int(token)
                    except ValueError:
                        token = token.lower()
            # Update parent pair with token
            if expr_stack:
                if field_stack[-1] == "cdr":
                    pair_stack[-1].cdr = token
                    field_stack[-1] = None
                else:
                    pair_stack[-1].car = token
            else:
                exprs.append(token)
    if expr_stack:
        raise ValueError(f'unclosed expression: {expr_stack}')
    return exprs

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
    exprs = parse(tokens)

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
    import pprint
    import sys
    with open(sys.argv[1] if len(sys.argv) >= 2 else 0) as file:
        text = file.read()
    tokens = tokenize(text)
    try:
        exprs = parse(tokens)
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
                exit(value)
        pprint.pp(value)

if __name__ == "__main__":
    main()
