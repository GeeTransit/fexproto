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

class Encapsulation:
    def __init__(self, obj, arg):
        self.obj = obj
        self.arg = arg

def f_eval(env, expr):
    if type(env) is dict:
        env = Environment(env, Environment.ROOT)
    continuation = Continuation(Environment.ROOT, _f_passthrough, Continuation.ROOT)
    continuation._call_info = ["f_eval", expr]
    continuation, value = Continuation(env, expr, continuation), None
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
    message_tree = Pair(parent, message_tree)
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
        elif type(obj) in (Environment, Continuation, Combiner, Encapsulation):
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

_FUNCTION_TYPE = type(lambda: None)
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
        continuation._call_info = ["eval combiner car", expr.car]  # non-tail call
        continuation = Continuation(env, name, continuation)
        return continuation, None
    elif type(expr) is not _FUNCTION_TYPE and type(expr) is not Operative:
        return parent, expr
    else:
        return expr(env, value, parent=parent)

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
def _encycle(a, c, args):
    if c == 0:
        return args
    for _ in range(a):
        args = args.cdr
    head = args
    for _ in range(c - 1):
        args = args.cdr
    args.cdr = head
    return args

def _step_call_combcar(_env, value, parent):
    if type(value) is not Combiner:
        return _f_error(parent, b"expected combiner as car of combiner call, got: ", value)
    return parent, value

# evaluate arguments based on num_wraps
def _step_call_wrapped(static, combiner, parent):
    env = static.bindings["env"]
    args = static.bindings["args"]
    assert type(combiner) is Combiner
    if combiner.num_wraps == 0 or args == ():
        continuation = Continuation(env, combiner.func, parent)
        return continuation, args
    p, n, a, c = _get_list_metrics(args)
    if n == c == 0:
        return _f_error(parent, b"applicative arguments must be proper list, got: ", args)
    # Create isomorphic list of args
    copy_args = last_arg = Pair((), ())
    curr_arg = args
    for _ in range(p):
        last_arg.cdr = Pair(curr_arg.car, ())
        last_arg = last_arg.cdr
        curr_arg = curr_arg.cdr
    copy_args = _encycle(a, c, copy_args.cdr)
    # Create list for order of argument evaluation
    eval_args = last_arg = Pair((), ())
    curr_arg = copy_args
    for _ in range(p):
        last_arg.cdr = Pair(curr_arg, ())
        last_arg = last_arg.cdr
        curr_arg = curr_arg.cdr
    eval_args = eval_args.cdr
    # Shuffle args to ensure correctness
    if p > 1:
        shuffle_args = []
        while eval_args != ():
            shuffle_args.append(eval_args.car)
            eval_args = eval_args.cdr
        import random; random.shuffle(shuffle_args)
        while shuffle_args:
            eval_args = Pair(shuffle_args.pop(), eval_args)
    # Setup and run _step_call_evcar on each argument
    next_env = Environment({
        "env": env,
        "combiner": combiner,
        "args": copy_args,
        "num_wraps": combiner.num_wraps,
        "p": p,
        "i": 0,
        "eval_args": eval_args,
        "eval_arg": eval_args,
    }, Environment.ROOT)
    continuation = Continuation(next_env, _step_call_evcar, parent)
    continuation._call_info = ["eval combiner arg", eval_args.car.car]
    continuation = Continuation(env, eval_args.car.car, continuation)
    return continuation, None

def _step_call_evcar(static, value, parent):
    env = static.bindings["env"]
    num_wraps = static.bindings["num_wraps"]
    p = static.bindings["p"]
    i = static.bindings["i"]
    eval_arg = static.bindings["eval_arg"]
    eval_arg.car.car = value
    i += 1
    eval_arg = eval_arg.cdr
    if i == p:
        i = 0
        num_wraps -= 1
        eval_arg = static.bindings["eval_args"]
        if num_wraps == 0:
            continuation = Continuation(env, static.bindings["combiner"].func, parent)
            return continuation, static.bindings["args"]
        static.bindings["num_wraps"] = num_wraps
    static.bindings["i"] = i
    static.bindings["eval_arg"] = eval_arg
    continuation = Continuation(static, _step_call_evcar, parent)
    continuation._call_info = ["eval combiner arg", eval_arg.car.car]
    continuation = Continuation(env, eval_arg.car.car, continuation)
    return continuation, None

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

def _f_force_normal_pass(env, value, parent):
    return env.bindings["continuation"], value

def _f_abnormal_pass(env, _value, parent):
    source = parent
    destination = env.parent.bindings["continuation"]
    def _get_continuation_depth(cont):
        depth = 0
        while cont is not Continuation.ROOT:
            cont = cont.parent
            depth += 1
        return depth
    def _continuation_contains(parent, child):
        while child is not Continuation.ROOT:
            if child is parent:
                return True
            child = child.parent
        return child is parent
    def _apply_interceptor(env, value, parent):
        outer = env.bindings["outer"]
        _, divert = _operative_continuation_to_applicative(Environment.ROOT, Pair(outer, ()), parent)
        return Continuation(Environment({}, Environment.ROOT), env.bindings["interceptor"].func, parent), Pair(value, Pair(divert, ()))
    # Get depth of source and destination continuation
    source_depth = _get_continuation_depth(source)
    destination_depth = _get_continuation_depth(destination)
    # Move up on both source and destination until a common ancestor is found
    source_curr = source
    destination_curr = destination
    exit_interceptors = []
    entry_interceptors = []
    while source_curr is not destination_curr:
        if source_depth > destination_depth:
            # Check exit guards
            if hasattr(source_curr, "exit_guards"):
                for selector, interceptor in source_curr.exit_guards:
                    if _continuation_contains(selector, destination):
                        exit_interceptors.append((source_curr, interceptor))
                        break
            source_curr = source_curr.parent
            source_depth -= 1
        else:
            # Check entry guards
            if hasattr(destination_curr, "entry_guards"):
                for selector, interceptor in destination_curr.entry_guards:
                    if _continuation_contains(selector, source):
                        entry_interceptors.append((destination_curr, interceptor))
                        break
            destination_curr = destination_curr.parent
            destination_depth -= 1
    # Setup interceptor chain
    next_cont = destination
    continuation = destination
    for cont, interceptor in entry_interceptors:
        continuation = Continuation(Environment({"continuation": next_cont}, Environment.ROOT), _f_force_normal_pass, cont)
        continuation = Continuation(Environment({"interceptor": interceptor, "outer": cont}, Environment.ROOT), _apply_interceptor, continuation)
        next_cont = cont
    for cont, interceptor in exit_interceptors:
        continuation = Continuation(Environment({"continuation": next_cont}, Environment.ROOT), _f_force_normal_pass, cont.parent)
        continuation = Continuation(Environment({"interceptor": interceptor, "outer": cont.parent}, Environment.ROOT), _apply_interceptor, continuation)
        next_cont = cont.parent
    return continuation, env.bindings["value"]

def _f_encapsulate(env, _value, parent):
    encap_arg = env.bindings["value"].car
    encap_obj = env.parent.bindings["encap_obj"]
    return parent, Encapsulation(encap_obj, encap_arg)

def _f_check_encapsulation(env, _value, parent):
    encap = env.bindings["value"].car
    encap_obj = env.parent.bindings["encap_obj"]
    return parent, type(encap) is Encapsulation and encap.obj is encap_obj

def _f_decapsulate(env, _value, parent):
    encap = env.bindings["value"].car
    encap_obj = env.parent.bindings["encap_obj"]
    if type(encap) is not Encapsulation or encap.obj is not encap_obj:
        return _f_error(parent, b"cannot decapsulate object", encap)
    return parent, encap.arg

def _f_dynamic_binder(env, _value, parent):
    value = env.bindings["value"].car
    combiner = env.bindings["value"].cdr.car
    dynamic_obj = env.parent.bindings["dynamic_obj"]
    if type(combiner) is not Combiner:
        return _f_error(parent, b"second argument must be a combiner", combiner)
    continuation = Continuation(Environment.ROOT, _f_passthrough, parent)
    continuation.dynamic_variables = {dynamic_obj: value}
    continuation = Continuation(Environment({}, Environment.ROOT), combiner.func, continuation)
    return continuation, ()

def _f_dynamic_accessor(env, _value, parent):
    dynamic_obj = env.parent.bindings["dynamic_obj"]
    continuation = parent
    while continuation is not Continuation.ROOT:
        if hasattr(continuation, "dynamic_variables"):
            for key, value in continuation.dynamic_variables.items():
                if key is dynamic_obj:
                    return parent, value
        continuation = continuation.parent
    return _f_error(parent, b"no dynamic binding found")

def _f_static_binder(env, _value, parent):
    value = env.bindings["value"].car
    environment = env.bindings["value"].cdr.car
    static_obj = env.parent.bindings["static_obj"]
    if type(environment) is not Environment:
        return _f_error(parent, b"second argument must be an environment", environment)
    environment = Environment({}, environment)
    environment.static_variables = {static_obj: value}
    return parent, environment

def _f_static_accessor(env, _value, parent):
    static_obj = env.parent.bindings["static_obj"]
    environment = env.bindings["dyn"]
    while environment is not Environment.ROOT:
        if hasattr(environment, "static_variables"):
            for key, value in environment.static_variables.items():
                if key is static_obj:
                    return parent, value
        environment = environment.parent
    return _f_error(parent, b"no static binding found")

def _f_passthrough(_env, value, parent):  # Useful for root REPL continuations
    return parent, value

def _f_sequence_inert(env, expr, parent):
    seq_env = env.bindings["env"]
    seq_exprs = env.bindings["exprs"]
    if seq_exprs == ():
        return parent, None
    next_env = Environment({"env": seq_env, "exprs": seq_exprs.cdr}, Environment.ROOT)
    continuation = Continuation(next_env, _f_sequence_inert, parent)
    continuation._call_info = ["eval sequence inert", seq_exprs.car]  # non-tail call
    continuation = Continuation(seq_env, seq_exprs.car, continuation)
    return continuation, None

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
    continuation._call_info = ["define value", expr.cdr.car]  # non-tail call
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

# load a file in an environment
def _operative_load(env, expr, parent):
    filename = expr.car
    filename_str = filename.decode("utf-8")
    with open(filename_str) as file:
        text = file.read()
    tokens = tokenize(text)
    try:
        exprs = parse(tokens, filename=filename_str)
    except ValueError as e:
        return _f_error(parent, b"error while loading file", filename, repr(e).encode("utf-8"))
    args = ()
    for expr in reversed(exprs): args = Pair(expr, args)
    next_env = Environment({"env": env, "exprs": args}, Environment.ROOT)
    continuation = Continuation(next_env, _f_sequence_inert, parent)
    return continuation, None

def _operative_if(env, expr, parent):
    next_env = Environment({"env": env, "on_true": expr.cdr.car, "on_false": expr.cdr.cdr.car}, Environment.ROOT)
    continuation = Continuation(next_env, _f_if, parent)
    continuation._call_info = ["if condition", expr.car]  # non-tail call
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
    combiner = expr.car
    if type(combiner) is not Combiner:
        return _f_error(parent, b"argument must be type Combiner, got: ", combiner)
    continuation = Continuation(env, combiner.func, parent)
    return continuation, Pair(parent, ())

def _operative_extend_continuation(env, expr, parent):
    continuation = expr.car
    applicative = expr.cdr.car
    environment = expr.cdr.cdr.car if expr.cdr.cdr != () else Environment({}, Environment.ROOT)
    if applicative.num_wraps != 1:
        return _f_error(parent, b"applicative unwrapped must be an operative")
    new_continuation = Continuation(environment, applicative.func, continuation)
    return parent, new_continuation

def _operative_guard_continuation(env, expr, parent):
    entry_guards = expr.car
    continuation = expr.cdr.car
    exit_guards = expr.cdr.cdr.car
    outer = Continuation(Environment.ROOT, _f_passthrough, continuation)
    outer.entry_guards = []
    inner = Continuation(Environment.ROOT, _f_passthrough, outer)
    inner.exit_guards = []
    for _ in range(_get_list_metrics(entry_guards)[0]):
        selector, interceptor = entry_guards.car.car, entry_guards.car.cdr.car
        if type(selector) is not Continuation:
            return _f_error(parent, b"selector must be a continuation")
        if type(interceptor) is not Combiner:
            return _f_error(parent, b"interceptor must be a applicative")
        if interceptor.num_wraps != 1:
            return _f_error(parent, b"interceptor unwrapped must be an operative")
        outer.entry_guards.append((selector, interceptor))
        entry_guards = entry_guards.cdr
    for _ in range(_get_list_metrics(exit_guards)[0]):
        selector, interceptor = exit_guards.car.car, exit_guards.car.cdr.car
        if type(selector) is not Continuation:
            return _f_error(parent, b"selector must be a continuation")
        if type(interceptor) is not Combiner:
            return _f_error(parent, b"interceptor must be a applicative")
        if interceptor.num_wraps != 1:
            return _f_error(parent, b"interceptor unwrapped must be an operative")
        inner.exit_guards.append((selector, interceptor))
        exit_guards = exit_guards.cdr
    return parent, inner

def _operative_make_encapsulation_type(env, expr, parent):
    encap_obj = object()
    encap_env = Environment({"encap_obj": encap_obj}, Environment.ROOT)
    encapsulator = Combiner(1, Operative(encap_env, "_", "value", _f_encapsulate))
    predicate = Combiner(1, Operative(encap_env, "_", "value", _f_check_encapsulation))
    decapsulator = Combiner(1, Operative(encap_env, "_", "value", _f_decapsulate))
    return parent, Pair(encapsulator, Pair(predicate, Pair(decapsulator, ())))

def _operative_make_keyed_dynamic_variable(env, expr, parent):
    dynamic_obj = object()
    dynamic_env = Environment({"dynamic_obj": dynamic_obj}, Environment.ROOT)
    binder = Combiner(1, Operative(dynamic_env, "_", "value", _f_dynamic_binder))
    accessor = Combiner(1, Operative(dynamic_env, "_", "value", _f_dynamic_accessor))
    return parent, Pair(binder, Pair(accessor, ()))

def _operative_make_keyed_static_variable(env, expr, parent):
    static_obj = object()
    static_env = Environment({"static_obj": static_obj}, Environment.ROOT)
    binder = Combiner(1, Operative(static_env, "_", "value", _f_static_binder))
    accessor = Combiner(1, Operative(static_env, "dyn", "value", _f_static_accessor))
    return parent, Pair(binder, Pair(accessor, ()))

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
    "guard-continuation": Combiner(1, _operative_guard_continuation),
    "error-continuation": Continuation.ERROR,
    "root-continuation": Continuation.ROOT,
    "make-encapsulation-type": Combiner(1, _operative_make_encapsulation_type),
    "make-keyed-dynamic-variable": Combiner(1, _operative_make_keyed_dynamic_variable),
    "make-keyed-static-variable": Combiner(1, _operative_make_keyed_static_variable),
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
        continuation = Continuation(Environment.ROOT, _f_passthrough, Continuation.ROOT)
        continuation._call_info = ["stdlib eval", expr]
        continuation, value = Continuation(env, expr, continuation), None
        while continuation is not Continuation.ROOT:
            continuation, value = step_evaluate(continuation, value)
            if continuation is Continuation.ERROR:
                raise ValueError(value)

    # return child of standard environment
    env = Environment({}, env)
    return env

def _f_print_trace(c):
    _FILE_LINES_CACHE = {}
    RJUST = 7

    # Print in reversed order to see the most relevant code earlier
    frames = []
    while c is not Continuation.ROOT:
        frames.append(c)
        c = c.parent

    for c in reversed(frames):
        if not hasattr(c, "_call_info"):
            continue

        if not hasattr(c._call_info[1], "_location_info"):
            print(f'  in unknown')
            print(end="".rjust(RJUST));_f_write(c._call_info[1]);print()
            continue

        filename, start_line, start_col, end_line, end_col = c._call_info[1]._location_info
        if filename not in _FILE_LINES_CACHE:
            _FILE_LINES_CACHE[filename] = None
            if filename[:1] != "\x00":
                try:
                    with open(filename) as _file: _text = _file.read()
                    _FILE_LINES_CACHE[filename] = _text.splitlines()
                except FileNotFoundError:
                    pass
        lines = _FILE_LINES_CACHE.get(filename)

        if filename[:1] == "\x00":
            filename = filename[1:]  # remove leading null

        if start_line == end_line:
            print(f'  in {filename!r} at {start_line} [{start_col}:{end_col}]')
        else:
            print(f'  in {filename!r} at {start_line}:{end_line} [{start_col}:{end_col}]')

        if lines is None:
            print(end="".rjust(RJUST));_f_write(c._call_info[1]);print()
            continue

        if start_line == end_line:
            # Single-line expression
            _line = lines[start_line-1]
            print(end=(str(start_line)+"|").rjust(RJUST))
            print(_line.expandtabs(4))
            print(end=(" "*(1+len(str(start_line)))).rjust(RJUST))
            _before = len(_line[:start_col-1].expandtabs(4))
            print(end=" "*_before)
            _after = len(_line[:end_col].expandtabs(4))
            print(end="~"*(_after-_before))
            print()

        else:
            # Multi-line expression
            for _line_no, _line in enumerate(lines[start_line-1:end_line], start=start_line):
                if _line_no == start_line:
                    _before = _line[:start_col-1].expandtabs(4)
                    _line = "".join(". "[char==" "] for char in _before) + _line.expandtabs(4)[len(_before):]
                elif _line_no == end_line:
                    _line = _line[:end_col].expandtabs(4) + "".join(". "[char==" "] for char in _line[end_col:].expandtabs(4))
                print(end=(str(_line_no).rjust(len(str(end_line)))+"|").rjust(RJUST))
                print(_line.expandtabs(4))

def main(env=None, argv=None):
    import sys
    if env is None:
        env = _make_standard_environment()
    if type(env) is dict:
        env = Environment(env, Environment.ROOT)
    if argv is None:
        argv = list(sys.argv)

    # Fake continuation to represent the interpreter
    main_continuation = Continuation(Environment.ROOT, _f_passthrough, Continuation.ROOT)

    interactive = (len(argv) == 1)

    with open(argv[1] if not interactive and argv[1] != "-" else 0, mode="rb") as file:
        reader = _Reader(lambda: file.read(1), argv[1] if not interactive else "\x00stdin")
        if interactive:
            print(f'? --- interactive repl ---')
            print(f'? results are prefixed with > and errors with !')
            print(f'? try typing (($lambda (a b) (+ a b)) 1 2)')
        while True:
            try:
                expr = reader.read()
            except EOFError:
                break
            except ValueError as e:
                if not interactive:
                    raise
                _syntax_error = Pair(type(e).__name__.encode("utf-8"), Pair(", ".join(e.args).encode("utf-8"), ()))
                print(end="! ");_f_write(Pair("syntax-error", _syntax_error));print()
                while reader.curr not in b"\n":
                    reader.next
                if reader.curr == b"":
                    break
                continue
            expr = _f_copy_es(expr, immutable=True)

            continuation = Continuation(Environment.ROOT, _f_passthrough, main_continuation)
            continuation._call_info = ["repl eval", expr]
            continuation, value = Continuation(env, expr, continuation), None
            while continuation is not Continuation.ROOT:
                try:
                    continuation, value = step_evaluate(continuation, value)
                except Exception as e:
                    value = Pair(continuation.parent, Pair(type(e).__name__.encode("utf-8"), Pair(", ".join(map(str, e.args)).encode("utf-8"), ())))
                    continuation = Continuation.ERROR
                    error_kind = "internal-error"
                else:
                    error_kind = "error"
                if continuation is Continuation.ERROR:
                    error_continuation = None
                    message = value
                    if type(message) is Pair and type(message.car) is Continuation:
                        print("! --- stack trace ---")
                        error_continuation, message = message.car, message.cdr
                        _f_print_trace(error_continuation)
                    print(end="! ");_f_write(Pair(error_kind, message));print()
                    if interactive:
                        env.bindings["last-error-continuation"] = error_continuation
                        env.bindings["last-error-message"] = message
                        break
                    exit(1)
                if continuation is main_continuation:
                    if interactive:
                        print(end="> ");_f_write(value);print()
                        env.bindings["last-value"] = value
                    break
            else:
                return

if __name__ == "__main__":
    main()
