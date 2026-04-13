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
Pair = namedtuple("Pair", "car cdr")
Eval = namedtuple("Eval", "env parent")
Env = namedtuple("Env", "items parent")
Combiner = namedtuple("Combiner", "num_wraps operative")
Combine = namedtuple("Combine", "operands dyn parent")
IfHelper = namedtuple("IfHelper", "then else_ dyn parent")
UserOp = namedtuple("UserOp", "static envname name body")
def lookup(env, symbol):
    if env is None:
        return None
    elif symbol in env.items:
        return env.items[symbol]
    else:
        return lookup(env.parent, symbol)
def plug(value, cont):
    match (value, cont):
        # Lookup symbols in current environment
        case (str(), Eval(env, parent)):
            return lookup(env, value), parent
        # Evaluate the car and combine the result with the cdr
        case (Pair(operator, operands), Eval(env, parent)):
            next_ = Combine(operands, env, parent)
            next2 = Eval(env, next_)
            return operator, next2
        # Everything else is self-evaluating
        case (value, Eval(env, parent)):
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
    raise NotImplementedError

assert plug(1, Eval(None, None)) == (1, None)
assert plug("var", Eval(Env({"var": 1}, None), None)) == (1, None)
assert plug("up", Eval(Env({"var": 1}, Env({"up": 2}, None)), None)) == (2, None)

def fully_evaluate(state):
    while True:
        # print(state)
        if state[1] is None:
            return state[0]
            break
        # input()
        state = plug(*state)

assert fully_evaluate((
    Pair("$if", Pair("var", Pair(1, Pair(2, ())))),
    Eval(Env({"$if": Combiner(0, "$if"), "var": False}, None), None),
)) == 2
assert fully_evaluate((
    Pair(Pair("$vau", Pair(Pair("dyn", Pair("args", ())), Pair("args", ()))), 1),
    Eval(Env({"$vau": Combiner(0, "$vau")}, None), None),
)) == 1
