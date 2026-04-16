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
EllipsisType = type(...)
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
def L(first, *args):
    args = [first] + list(args)
    result = args.pop()
    while args:
        result = Pair(args.pop(), result)
    return result
def plug(value, cont):
    match (value, cont):
        # Lookup symbols in current environment
        case (str() as name, Eval(Env(items, env_parent), parent)) if name in items:
            return items[name], parent
        case (str() as name, Eval(Env(items, env_parent), parent)):
            next_ = Eval(env_parent, parent)
            return name, next_
        case (str() as name, Eval(None, parent)):
            raise LookupError(name)
        # Evaluate the car and combine the result with the cdr
        case (Pair(operator, operands), Eval(env, parent)):
            next_ = Combine(operands, env, parent)
            next2 = Eval(env, next_)
            return operator, next2
        # Everything else is self-evaluating
        case (value, Eval(env, parent)) if not isinstance(value, Unknown):
            return value, parent
        # Handle $if primitive
        case (Combiner(0, "$if"), Combine(Pair(cond, Pair(then, Pair(else_, ()))), dyn, parent)):
            next_ = IfHelper(then, else_, dyn, parent)
            next2 = Eval(dyn, next_)
            return cond, next2
        case (True, IfHelper(then, else_, dyn, parent)):
            next_ = Eval(dyn, parent)
            return then, next_
        case (False, IfHelper(then, else_, dyn, parent)):
            next_ = Eval(dyn, parent)
            return else_, next_
        # Handle user defined operatives from $vau
        case (Combiner(0, "$vau"), Combine(Pair(Pair((str() | EllipsisType()) as envname, Pair(str() as name, ())), Pair(body, ())), dyn, parent)):
            operative = UserOp(dyn, envname, name, body)
            combiner = Combiner(0, operative)
            return combiner, parent
        case (Combiner(0, UserOp(static, EllipsisType(), name, body)), Combine(operands, dyn, parent)):
            env = Env({
                name: operands,
            }, static)
            next_ = Eval(env, parent)
            return body, next_
        case (Combiner(0, UserOp(static, envname, name, body)), Combine(operands, dyn, parent)):
            env = Env({
                envname: dyn,
                name: operands,
            }, static)
            next_ = Eval(env, parent)
            return body, next_
        # Handle more primitives
        case (Combiner(0, "cons"), Combine(Pair(car, Pair(cdr, ())), dyn, parent)):
            return Pair(car, cdr), parent
        case (Combiner(0, "car"), Combine(Pair(Pair(car, cdr), ()), dyn, parent)):
            return car, parent
        case (Combiner(0, "cdr"), Combine(Pair(Pair(car, cdr), ()), dyn, parent)):
            return cdr, parent
        case (Combiner(0, "eval"), Combine(Pair(env, Pair(expr, ())), dyn, parent)):
            next_ = Eval(env, parent)
            return expr, next_
        # Handle wrapped operatives
        case (Combiner(int() as num_wraps, operative) as combiner, Combine(operands, dyn, parent)) if num_wraps > 0:
            next_ = EvLis(combiner, (), dyn, parent)
            return operands, next_
        case ((), EvLis(combiner, rev_args, dyn, parent)):
            return rev_args, EvRev(combiner, (), dyn, parent)
        case (Pair(operand, rest_operands), EvLis(combiner, rev_args, dyn, parent)):
            next_ = EvArg(combiner, rev_args, rest_operands, dyn, parent)
            next2 = Eval(dyn, next_)
            return operand, next2
        case (value, EvArg(combiner, rev_args, rest_operands, dyn, parent)):
            next_ = EvLis(combiner, Pair(value, rev_args), dyn, parent)
            return rest_operands, next_
        case ((), EvRev(combiner, args, dyn, parent)):
            unwrapped = Combiner(combiner.num_wraps - 1, combiner.operative)
            next_ = Combine(args, dyn, parent)
            return unwrapped, next_
        case (Pair(arg, restArgs), EvRev(combiner, args, dyn, parent)):
            next_ = EvRev(combiner, Pair(arg, args), dyn, parent)
            return restArgs, next_
    raise NotImplementedError

assert plug(1, Eval(None, None)) == (1, None)
assert plug("var", Eval(Env({"var": 1}, None), None)) == (1, None)
assert plug(*plug("up", Eval(Env({"var": 1}, Env({"up": 2}, None)), None))) == (2, None)

def fully_evaluate(state):
    while True:
        # print(state)
        if state[1] is None:
            return state[0]
            break
        # input()
        if state[2] is None:
            return state[1]
        try:
            state = plug(*state)
        except NotImplementedError as e:
            raise NotImplementedError(state) from e

assert fully_evaluate((
    Pair("$if", Pair("var", Pair(1, Pair(2, ())))),
    Eval(Env({"$if": Combiner(0, "$if"), "var": False}, None), None),
)) == 2
assert fully_evaluate((
    Pair(Pair("$vau", Pair(Pair("dyn", Pair("args", ())), Pair("args", ()))), 1),
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
    assert hole[0] is var
    assert isinstance(hole[1], IfHelper)
    assert fully_evaluate((True, hole[1])) == 2
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
    assert isinstance(hole[0], Combiner)
    assert hole[0][1] == "car"
    assert isinstance(hole[1], Combine)
    ctx.metadata[var] = Pair(True, False)
    assert fully_evaluate(hole) == 1
    ctx.metadata[var] = Pair(False, True)
    assert fully_evaluate(hole) == 2
    ctx.metadata[var] = Pair(False, False)
    assert fully_evaluate(hole) == 3
test_hole2()
