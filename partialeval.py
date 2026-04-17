'''
symbol -> eval env parent
  value = env.lookup(symbol)
  value -> parent
(operator . operands) -> eval env parent
  next = combine operands env parent
  operator -> eval env next
combiner(num_wraps=0, if) -> combine operands dyn parent
  (cond then else) = operands
  next = if-helper then else dyn parent
  cond -> eval dyn next
combiner(num_wraps=0, operative(static, envname, name, expr)) -> combine operands dyn parent
  env = new Environment(static)
  env.assign(envname, dyn)
  env.assign(name, operands)
  expr -> eval env parent
combiner(num_wraps=..., ...) -> combine operands dyn parent
  operands -> evlis combiner () dyn parent
() -> evlis combiner revArguments dyn parent
  combiner.unwrap() -> combine reverse(revArguments) dyn parent
(operand . operands) -> evlis combiner revArguments dyn parent
  rest = evarg combiner revArguments operands dyn parent
  operand -> eval dyn rest
value -> evarg combiner revArguments operands dyn parent
  operands -> evlis combiner cons(value, revArguments) dyn parent
#t -> if-helper then else dyn parent
  then -> eval dyn parent
#f -> if-helper then else dyn parent
  else -> eval dyn parent


when we evaluate an expression, track the steps made and follow the steps, guarding before each step
'''

# try simplifying a $cond
# symbols are str
#
from collections import namedtuple
class ContextMeta(type):
    def __instancecheck__(self, instance):
        if type(instance) is Unknown:
            instance = instance.ctx.metadata.get(instance)
        return issubclass(type(instance), self)
def wrap(cls):
    import functools
    class _WrapperClass(cls, metaclass=ContextMeta): pass
    functools.update_wrapper(_WrapperClass, cls, updated=())
    return _WrapperClass
def wrapnamedtuple(name, attrs):
    return wrap(namedtuple(name, attrs))
Pair = wrapnamedtuple("Pair", "car cdr")
Eval = wrapnamedtuple("Eval", "env parent")
Env = wrapnamedtuple("Env", "items parent")
Combiner = wrapnamedtuple("Combiner", "num_wraps operative")
Combine = wrapnamedtuple("Combine", "operands dyn parent")
IfHelper = wrapnamedtuple("IfHelper", "then else_ dyn parent")
UserOp = wrapnamedtuple("UserOp", "static envname name body")
EvLis = wrapnamedtuple("EvLis", "combiner rev_args dyn parent")
EvArg = wrapnamedtuple("EvArg", "combiner rev_args rest_operands dyn parent")
EvRev = wrapnamedtuple("EvRev", "combiner args dyn parent")
Sym = wrapnamedtuple("Sym", "name")
Bool = wrapnamedtuple("Bool", "value")
Nil = wrapnamedtuple("Nil", "")
Ignore = wrapnamedtuple("Ignore", "")
class Unknown:
    def __init__(self, name=None, ctx=None):
        if name is None:
            name = str(hex(id(ctx)))
        self.name = name
        self.ctx = ctx
    import reprlib
    @reprlib.recursive_repr()
    def __repr__(self):
        if self in self.ctx.metadata:
            return f'<{self.name}: {self.ctx.metadata[self]!r}>'
        return f'<{self.name}>'
    def __getattr__(self, name):
        return getattr(self.ctx.metadata[self], name)
class Context:
    def __init__(self, metadata):
        self.metadata = metadata
def L(first, *rest):
    args = []
    for arg in [first] + list(rest):
        if arg == ():
            arg = Nil()
        elif isinstance(arg, str):
            arg = Sym(arg)
        elif isinstance(arg, bool):
            arg = Bool(arg)
        args.append(arg)
    result = args.pop()
    while args:
        result = Pair(args.pop(), result)
    return result
def plug(instr, value, cont):
    match (instr, value, cont):
        # Lookup symbols in current environment
        case ("lookup]" | None, Sym(name), Eval(Env(items, env_parent), parent)) if name in items:
            if instr is None: return "lookup]", value, cont
            return None, items[name], parent
        case ("lookup_enclosing" | None, Sym(name), Eval(Env(items, env_parent), parent)) if name not in items:
            if instr is None: return "lookup_enclosing", value, cont
            next_ = Eval(env_parent, parent)
            return None, Sym(name), next_
        case ("lookup_fail!" | None, Sym(name), Eval(None, parent)):
            if instr is None: return "lookup_fail!", value, cont
            raise LookupError(name)
        # Evaluate the car and combine the result with the cdr
        case ("combine[" | None, Pair(operator, operands), Eval(env, parent)):
            if instr is None: return "combine[", value, cont
            next_ = Combine(operands, env, parent)
            next2 = Eval(env, next_)
            return None, operator, next2
        # Everything else is self-evaluating
        case ("self_eval]" | None, value, Eval(env, parent)) if not isinstance(value, (Sym, Pair)) and (not isinstance(value, Unknown) or value in value.ctx.metadata):
            if instr is None: return "self_eval]", value, cont
            return None, value, parent
        # Handle $if primitive
        case ("if[" | None, Combiner(0, "$if"), Combine(Pair(cond, Pair(then, Pair(else_, Nil()))), dyn, parent)):
            if instr is None: return "if[", value, cont
            next_ = IfHelper(then, else_, dyn, parent)
            next2 = Eval(dyn, next_)
            return None, cond, next2
        case ("if_true" | None, Bool(True), IfHelper(then, else_, dyn, parent)):
            if instr is None: return "if_true", value, cont
            next_ = Eval(dyn, parent)
            return None, then, next_
        case ("if_false" | None, Bool(False), IfHelper(then, else_, dyn, parent)):
            if instr is None: return "if_false", value, cont
            next_ = Eval(dyn, parent)
            return None, else_, next_
        # Handle user defined operatives from $vau
        case ("vau]" | None, Combiner(0, "$vau"), Combine(Pair(Pair((Sym() | Ignore()) as envname, Pair(Sym() as name, Nil())), Pair(body, Nil())), dyn, parent)):
            if instr is None: return "vau]", value, cont
            operative = UserOp(dyn, envname, name, body)
            combiner = Combiner(0, operative)
            return None, combiner, parent
        case ("call_ignore_env" | None, Combiner(0, UserOp(static, Ignore(), Sym(name), body)), Combine(operands, dyn, parent)):
            if instr is None: return "call_ignore_env", value, cont
            env = Env({
                name: operands,
            }, static)
            next_ = Eval(env, parent)
            return None, body, next_
        case ("call" | None, Combiner(0, UserOp(static, Sym(envname), Sym(name), body)), Combine(operands, dyn, parent)):
            if instr is None: return "call", value, cont
            env = Env({
                envname: dyn,
                name: operands,
            }, static)
            next_ = Eval(env, parent)
            return None, body, next_
        # Handle more primitives
        case ("cons]" | None, Combiner(0, "cons"), Combine(Pair(car, Pair(cdr, Nil())), dyn, parent)):
            if instr is None: return "cons]", value, cont
            return None, Pair(car, cdr), parent
        case ("car]" | None, Combiner(0, "car"), Combine(Pair(Pair(car, cdr), Nil()), dyn, parent)):
            if instr is None: return "car]", value, cont
            return None, car, parent
        case ("cdr]" | None, Combiner(0, "cdr"), Combine(Pair(Pair(car, cdr), Nil()), dyn, parent)):
            if instr is None: return "cdr]", value, cont
            return None, cdr, parent
        case ("eval" | None, Combiner(0, "eval"), Combine(Pair(env, Pair(expr, Nil())), dyn, parent)):
            if instr is None: return "eval", value, cont
            next_ = Eval(env, parent)
            return None, expr, next_
        # Handle wrapped operatives
        case ("apply" | None, Combiner(int() as num_wraps, operative) as combiner, Combine(operands, dyn, parent)) if num_wraps > 0:
            if instr is None: return "apply", value, cont
            next_ = EvLis(combiner, Nil(), dyn, parent)
            return None, operands, next_
        case ("evlis_empty" | None, Nil(), EvLis(combiner, rev_args, dyn, parent)):
            if instr is None: return "evlis_empty", value, cont
            next_ = EvRev(combiner, Nil(), dyn, parent)
            return None, rev_args, next_
        case ("evlis[" | None, Pair(operand, rest_operands), EvLis(combiner, rev_args, dyn, parent)):
            if instr is None: return "evlis[", value, cont
            next_ = EvArg(combiner, rev_args, rest_operands, dyn, parent)
            next2 = Eval(dyn, next_)
            return None, operand, next2
        case ("evarg" | None, value, EvArg(combiner, rev_args, rest_operands, dyn, parent)):
            if instr is None: return "evarg", value, cont
            next_ = EvLis(combiner, Pair(value, rev_args), dyn, parent)
            return None, rest_operands, next_
        case ("evrev_empty" | None, Nil(), EvRev(combiner, args, dyn, parent)):
            if instr is None: return "evrev_empty", value, cont
            unwrapped = Combiner(combiner.num_wraps - 1, combiner.operative)
            next_ = Combine(args, dyn, parent)
            return None, unwrapped, next_
        case ("evrev" | None, Pair(arg, restArgs), EvRev(combiner, args, dyn, parent)):
            if instr is None: return "evrev", value, cont
            next_ = EvRev(combiner, Pair(arg, args), dyn, parent)
            return None, restArgs, next_
    raise NotImplementedError

# assert plug(1, Eval(None, None)) == (1, None)
# assert plug(Sym("var"), Eval(Env({"var": 1}, None), None)) == (1, None)
# assert plug(*plug(Sym("up"), Eval(Env({"var": 1}, Env({"up": 2}, None)), None))) == (2, None)

def fully_evaluate(state):
    state = None, *state
    while True:
        # print(state)
        # input()
        if state[2] is None:
            return state[1]
        try:
            state = plug(*state)
        except NotImplementedError as e:
            raise NotImplementedError(state) from e
def record_trace(state):
    instrs = []
    while True:
        if state[2] is None:
            return instrs, state[1]
        try:
            state = plug(*state)
        except NotImplementedError as e:
            raise NotImplementedError(state) from e
        if state[0] is not None:
            instrs.append(state[0])
def run_trace(instrs, state):
    for instr in instrs:
        try:
            state = plug(instr, *state[1:])
        except NotImplementedError as e:
            raise NotImplementedError(state) from e
    return state

assert fully_evaluate((
    Pair(Sym("$if"), Pair(Sym("var"), Pair(1, Pair(2, Nil())))),
    Eval(Env({"$if": Combiner(0, "$if"), "var": Bool(False)}, None), None),
)) == 2
assert fully_evaluate((
    Pair(Pair(Sym("$vau"), Pair(Pair(Sym("dyn"), Pair(Sym("args"), Nil())), Pair(Sym("args"), Nil()))), 1),
    Eval(Env({"$vau": Combiner(0, "$vau")}, None), None),
)) == 1
cond = fully_evaluate((
    L("$vau", L("dyn", "args", ()),
        L("$if", L("eval", "dyn", L("car", L("car", "args", ()), ()), ()),
            L("eval", "dyn", L("car", L("cdr", L("car", "args", ()), ()), ()), ()),
            L("eval", "dyn", L("cons", "$cond", L("cdr", "args", ()), ()), ()),
        ()),
    ()),
    Eval(Env({
        "$vau": Combiner(0, "$vau"),
        "$if": Combiner(0, "$if"),
        "eval": Combiner(1, "eval"),
        "car": Combiner(1, "car"),
        "cdr": Combiner(1, "cdr"),
        "cons": Combiner(1, "cons"),
    }, None), None),
))
cond.operative.static.items["$cond"] = cond
assert fully_evaluate((
    L("$cond", L(False, 1, ()), L(True, 2, ()), ()),
    Eval(cond.operative.static, None),
)) == 2

def test_hole():
    ctx = Context({})
    var = Unknown("var", ctx)
    env = Env({"var": var}, cond.operative.static)
    try:
        fully_evaluate((
            L("$cond", L(False, 1, ()), L("var", 2, ()), ()),
            Eval(env, None),
        ))
    except NotImplementedError as e:
        hole = e.args[0]
    assert hole[1] is var
    assert isinstance(hole[2], IfHelper)
    assert fully_evaluate((Bool(True), hole[2])) == 2
test_hole()

def test_hole2():
    ctx = Context({})
    var = Unknown("var", ctx)
    env = Env({"var": var}, cond.operative.static)
    try:
        fully_evaluate((
            L("$cond",
                L(L("car", "var", ()), 1, ()),
                L(L("cdr", "var", ()), 2, ()),
                L(True, 3, ()),
            ()),
            Eval(env, None),
        ))
    except NotImplementedError as e:
        hole = e.args[0]
    assert isinstance(hole[1], Combiner)
    assert hole[1][1] == "car"
    assert isinstance(hole[2], Combine)
    ctx.metadata[var] = Pair(Bool(True), Bool(False))
    assert fully_evaluate(hole[1:]) == 1
    ctx.metadata[var] = Pair(Bool(False), Bool(True))
    assert fully_evaluate(hole[1:]) == 2
    ctx.metadata[var] = Pair(Bool(False), Bool(False))
    assert fully_evaluate(hole[1:]) == 3
test_hole2()

def test_trace():
    ctx = Context({})
    var = Unknown("var", ctx)
    ctx.metadata[var] = Pair(Bool(False), Bool(True))
    env = Env({"var": var}, cond.operative.static)
    state = (
        L("$cond",
            L(L("car", "var", ()), 1, ()),
            L(L("cdr", "var", ()), 2, ()),
            L(True, 3, ()),
        ()),
        Eval(env, None),
    )
    steps, result = record_trace((None, *state))
    assert result == 2
    final = run_trace(steps, (None, *state))
    print(*steps)
    assert final[1] == 2
    assert final[2] is None
test_trace()
